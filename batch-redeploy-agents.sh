#!/bin/bash
# Batch redeploy all deployed remote agents in parallel
# This rebuilds Docker images with the updated agent names and pushes to Azure
# Branding already redeployed — skip it.

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 15 remaining deployed agents (branding already done): directory_name:port
AGENTS=(
    "azurefoundry_classification:8001"
    "azurefoundry_image_generator:9010"
    "azurefoundry_video:9028"
    "azurefoundry_QuickBooks:8020"
    "azurefoundry_Stripe:9030"
    "azurefoundry_HubSpot:9042"
    "azurefoundry_twilio2:8016"
    "azurefoundry_email:9029"
    "azurefoundry_teams:8021"
    "azurefoundry_Word:9038"
    "azurefoundry_Excel:9037"
    "azurefoundry_PowerPoint:9036"
    "azurefoundry_StockMarket:9040"
    "azurefoundry_Music:9044"
    "azurefoundry_VideoAudio:9045"
)

LOG_DIR="/tmp/agent-deploy-logs"
mkdir -p "$LOG_DIR"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Batch Agent Redeployment (${#AGENTS[@]} agents)${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Login to ACR once
echo -e "${CYAN}Logging in to ACR...${NC}"
az acr login --name a2awestuslab
echo ""

PIDS=()
AGENT_NAMES=()

for entry in "${AGENTS[@]}"; do
    AGENT_NAME="${entry%%:*}"
    PORT="${entry##*:}"
    LOG_FILE="$LOG_DIR/${AGENT_NAME}.log"

    echo -e "${YELLOW}Starting deploy: $AGENT_NAME (port $PORT)${NC}"

    # Run deploy script in background, capturing output
    ./deploy-remote-agent.sh -a "$AGENT_NAME" -p "$PORT" > "$LOG_FILE" 2>&1 &
    PIDS+=($!)
    AGENT_NAMES+=("$AGENT_NAME")
done

echo ""
echo -e "${CYAN}All ${#PIDS[@]} deployments launched. Waiting for completion...${NC}"
echo ""

# Wait for all and report results
FAILED=0
for i in "${!PIDS[@]}"; do
    PID=${PIDS[$i]}
    NAME=${AGENT_NAMES[$i]}

    if wait "$PID"; then
        echo -e "${GREEN}  DONE: $NAME${NC}"
    else
        echo -e "${RED}  FAIL: $NAME (see $LOG_DIR/${NAME}.log)${NC}"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  All ${#AGENTS[@]} agents deployed successfully!${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  $FAILED of ${#AGENTS[@]} deployments failed${NC}"
    echo -e "${RED}  Check logs in: $LOG_DIR/${NC}"
    echo -e "${RED}========================================${NC}"
fi
