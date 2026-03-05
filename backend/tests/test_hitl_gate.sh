#!/usr/bin/env bash
# =============================================================================
# HITL Gate E2E Test Script
#
# Tests the Human-in-the-Loop gate: after a HITL agent (Teams/SMS) pauses a
# workflow and the human responds, the orchestrator LLM evaluates whether the
# workflow should continue or stop.
#
# Usage:
#   ./backend/tests/test_hitl_gate.sh                  # Interactive (waits for you to respond in Teams)
#   ./backend/tests/test_hitl_gate.sh --check <convid> # Just check logs for a previous test
#
# Prerequisites:
#   - az CLI logged in (for log checking)
#   - Teams bot running and reachable
#   - Backend deployed with HITL gate code
# =============================================================================
set -euo pipefail

BASE_URL="${HITL_TEST_URL:-https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io}"
EMAIL="${HITL_TEST_EMAIL:-test@example.com}"
PASSWORD="${HITL_TEST_PASSWORD:-test123}"
SESSION_ID="${HITL_TEST_SESSION:-hitl_test}"
RESOURCE_GROUP="${HITL_TEST_RG:-rg-a2a-prod}"
CONTAINER_APP="${HITL_TEST_APP:-backend-uami}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
bold() { echo -e "${BOLD}$*${NC}"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
login() {
    local resp
    resp=$(curl -sf -X POST "$BASE_URL/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" 2>/dev/null) || {
        fail "Login failed — is the backend running?"
        exit 1
    }
    TOKEN=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
    USER_ID=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('user_info',{}).get('user_id',''))")
    if [[ -z "$TOKEN" ]]; then
        fail "No access_token in login response"
        exit 1
    fi
    pass "Logged in as $EMAIL (user_id=$USER_ID)"
}

enable_agent() {
    local agent_name_filter="$1"
    local config
    config=$(curl -sf "$BASE_URL/agents/catalog" 2>/dev/null | python3 -c "
import sys, json
agents = json.load(sys.stdin).get('agents', [])
for a in agents:
    if '${agent_name_filter}'.lower() in a.get('name','').lower():
        print(json.dumps(a))
        break
" 2>/dev/null)

    if [[ -z "$config" ]]; then
        fail "Agent matching '$agent_name_filter' not found in catalog"
        return 1
    fi

    local agent_name
    agent_name=$(echo "$config" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))")

    local resp
    resp=$(curl -sf -X POST "$BASE_URL/agents/session/enable" \
        -H "Content-Type: application/json" \
        -d "{\"session_id\":\"$SESSION_ID\",\"agent\":$config}" 2>/dev/null)

    local status
    status=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
    if [[ "$status" == "success" ]]; then
        pass "Enabled: $agent_name"
    else
        warn "Enable response for $agent_name: $resp"
    fi
}

send_query() {
    local query="$1"
    local conv_id
    conv_id=$(python3 -c "import uuid; print(str(uuid.uuid4()))")

    log "Sending query (conversation_id=$conv_id)..."
    local resp
    resp=$(curl -sf --max-time 180 -X POST "$BASE_URL/api/query" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d "{
            \"query\": $(python3 -c "import json; print(json.dumps('$query'))"),
            \"user_id\": \"$USER_ID\",
            \"session_id\": \"$SESSION_ID\",
            \"conversation_id\": \"$conv_id\"
        }" 2>/dev/null) || {
        fail "Query request failed or timed out"
        echo "$conv_id"
        return 1
    }

    local success
    success=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success',False))" 2>/dev/null)
    local result
    result=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result','')[:200])" 2>/dev/null)

    if [[ "$success" == "True" ]]; then
        pass "Query accepted (${result})"
    else
        fail "Query failed: $result"
    fi

    echo "$conv_id"
}

check_logs() {
    local conv_id="$1"
    local pattern="$2"
    local context_id="${SESSION_ID}::${conv_id}"

    log "Checking Azure logs for context: $context_id"
    log "Looking for: $pattern"

    local logs
    logs=$(az containerapp logs show \
        --name "$CONTAINER_APP" \
        --resource-group "$RESOURCE_GROUP" \
        --type console --tail 400 2>&1 \
        | grep -E "$context_id" \
        | grep -iE "$pattern" \
        | tail -10)

    if [[ -n "$logs" ]]; then
        pass "Found matching log entries:"
        echo "$logs" | while IFS= read -r line; do
            local ts msg
            ts=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('TimeStamp','')[:19])" 2>/dev/null || echo "?")
            msg=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Log','')[2:][:200])" 2>/dev/null || echo "$line")
            echo -e "  ${CYAN}$ts${NC} $msg"
        done
        return 0
    else
        warn "No matching logs yet"
        return 1
    fi
}

wait_for_log() {
    local conv_id="$1"
    local pattern="$2"
    local label="$3"
    local max_wait="${4:-120}"
    local interval=15
    local elapsed=0

    log "Waiting for: $label (timeout: ${max_wait}s)"
    while (( elapsed < max_wait )); do
        if check_logs "$conv_id" "$pattern" 2>/dev/null; then
            return 0
        fi
        elapsed=$((elapsed + interval))
        if (( elapsed < max_wait )); then
            echo -ne "  Waiting... (${elapsed}s/${max_wait}s)\r"
            sleep "$interval"
        fi
    done
    fail "Timed out waiting for: $label"
    return 1
}

show_hitl_summary() {
    local conv_id="$1"
    local context_id="${SESSION_ID}::${conv_id}"

    bold "\n=== HITL Gate Summary for $conv_id ==="

    local logs
    logs=$(az containerapp logs show \
        --name "$CONTAINER_APP" \
        --resource-group "$RESOURCE_GROUP" \
        --type console --tail 400 2>&1 \
        | grep "$context_id")

    # Check each stage
    local stage_patterns=(
        "HITL RESUME|hitl_resume_detected:HITL Resume Detection"
        "MODE DETECT.*use_orchestration=True:Orchestration Mode"
        "HITL Gate.*should_continue|hitl_gate:HITL Gate Evaluation"
        "Workflow stopped|gate_stop:Workflow Stopped (rejection)"
        "Outlook Agent|Email.*Step:Email Step (continuation)"
    )

    for entry in "${stage_patterns[@]}"; do
        local pattern="${entry%%:*}"
        local label="${entry##*:}"
        if echo "$logs" | grep -qiE "$pattern"; then
            pass "$label"
        else
            echo -e "  ${YELLOW}[ -- ]${NC} $label (not found)"
        fi
    done
    echo ""
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
test_rejection() {
    bold "\n=========================================="
    bold "  TEST: HITL Gate — Rejection Flow"
    bold "  Respond 'I do not approve' in Teams"
    bold "=========================================="

    local conv_id
    conv_id=$(send_query "Use the Microsoft Teams Agent to ask Simon Lacasse if he approves the quarterly budget of \$50,000. After he responds, use the Microsoft Outlook Agent to email a summary to simon.lacasse@gmail.com")

    log "Workflow should be paused — waiting for Teams message to arrive..."
    echo ""
    bold "  >>> Go to Teams and respond: 'I do not approve' <<<"
    echo ""

    read -rp "Press Enter after you've responded in Teams (or 'skip' to just check logs): " user_input

    if [[ "$user_input" == "skip" ]]; then
        show_hitl_summary "$conv_id"
        return
    fi

    log "Waiting for HITL gate to evaluate..."
    sleep 10

    if wait_for_log "$conv_id" "HITL Gate.*Stopping|gate_stop|should_continue.*false" "HITL gate stop" 90; then
        pass "HITL gate correctly STOPPED the workflow"
    else
        fail "HITL gate did not stop — checking full summary..."
    fi

    show_hitl_summary "$conv_id"
}

test_approval() {
    bold "\n=========================================="
    bold "  TEST: HITL Gate — Approval Flow"
    bold "  Respond 'Yes, approved' in Teams"
    bold "=========================================="

    local conv_id
    conv_id=$(send_query "Use the Microsoft Teams Agent to ask Simon Lacasse if he approves the marketing budget of \$25,000. After he responds, use the Microsoft Outlook Agent to email a summary of his decision to simon.lacasse@gmail.com")

    log "Workflow should be paused — waiting for Teams message to arrive..."
    echo ""
    bold "  >>> Go to Teams and respond: 'Yes, approved' <<<"
    echo ""

    read -rp "Press Enter after you've responded in Teams (or 'skip' to just check logs): " user_input

    if [[ "$user_input" == "skip" ]]; then
        show_hitl_summary "$conv_id"
        return
    fi

    log "Waiting for HITL gate to evaluate..."
    sleep 10

    if wait_for_log "$conv_id" "HITL Gate.*Continuing|should_continue.*true|Outlook Agent|Email.*Step" "HITL gate continue + email step" 120; then
        pass "HITL gate correctly CONTINUED the workflow"
    else
        fail "HITL gate did not continue — checking full summary..."
    fi

    show_hitl_summary "$conv_id"
}

test_info_response() {
    bold "\n=========================================="
    bold "  TEST: HITL Gate — Info Response Flow"
    bold "  Respond with requested info in Teams"
    bold "=========================================="

    local conv_id
    conv_id=$(send_query "Use the Microsoft Teams Agent to ask Simon Lacasse what color theme he prefers for the new website (blue, green, or red). After he responds, use the Microsoft Outlook Agent to email his choice to simon.lacasse@gmail.com")

    log "Workflow should be paused — waiting for Teams message to arrive..."
    echo ""
    bold "  >>> Go to Teams and respond with a color, e.g.: 'I prefer blue' <<<"
    echo ""

    read -rp "Press Enter after you've responded in Teams (or 'skip' to just check logs): " user_input

    if [[ "$user_input" == "skip" ]]; then
        show_hitl_summary "$conv_id"
        return
    fi

    log "Waiting for HITL gate to evaluate..."
    sleep 10

    if wait_for_log "$conv_id" "HITL Gate.*Continuing|should_continue.*true|Outlook Agent|Email.*Step" "HITL gate continue + email step" 120; then
        pass "HITL gate correctly CONTINUED the workflow"
    else
        fail "HITL gate did not continue — checking full summary..."
    fi

    show_hitl_summary "$conv_id"
}

check_only() {
    local conv_id="$1"
    bold "\n=== Checking logs for conversation: $conv_id ==="
    show_hitl_summary "$conv_id"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    bold "HITL Gate E2E Test Suite"
    bold "Backend: $BASE_URL"
    echo ""

    # Handle --check mode
    if [[ "${1:-}" == "--check" ]]; then
        if [[ -z "${2:-}" ]]; then
            fail "Usage: $0 --check <conversation_id>"
            exit 1
        fi
        login
        check_only "$2"
        exit 0
    fi

    # Setup
    login
    log "Enabling agents for session '$SESSION_ID'..."
    enable_agent "teams"
    enable_agent "outlook"
    echo ""

    # Menu
    if [[ "${1:-}" == "--all" ]]; then
        test_rejection
        echo ""
        warn "Wait ~20s between tests to avoid rate limits"
        sleep 20
        test_approval
        sleep 20
        test_info_response
    elif [[ "${1:-}" == "--rejection" || "${1:-}" == "-r" ]]; then
        test_rejection
    elif [[ "${1:-}" == "--approval" || "${1:-}" == "-a" ]]; then
        test_approval
    elif [[ "${1:-}" == "--info" || "${1:-}" == "-i" ]]; then
        test_info_response
    else
        bold "Select a test case:"
        echo "  1) Rejection  — respond 'I do not approve'  → gate should STOP"
        echo "  2) Approval   — respond 'Yes, approved'     → gate should CONTINUE"
        echo "  3) Info       — respond with requested info  → gate should CONTINUE"
        echo "  4) Run all three sequentially"
        echo ""
        read -rp "Choice [1-4]: " choice
        case "$choice" in
            1) test_rejection ;;
            2) test_approval ;;
            3) test_info_response ;;
            4)
                test_rejection
                warn "Wait ~20s between tests to avoid rate limits"
                sleep 20
                test_approval
                sleep 20
                test_info_response
                ;;
            *) fail "Invalid choice"; exit 1 ;;
        esac
    fi

    bold "\nDone."
}

main "$@"
