# Contoso Technical Dispatch Agent

Final decision agent for Contoso customer support workflow with Human-in-the-Loop capability for complex escalations.

## Overview

This agent serves as the final decision point in the Contoso internet troubleshooting workflow. After all diagnostic agents (Authentication, Outage Check, Modem Check, Internet Plan, Network Performance) have completed their analysis, this agent determines the appropriate resolution:

1. **Schedule Technician Appointment**: For confirmed hardware/infrastructure issues requiring physical intervention
2. **Escalate to Human Expert**: For complex edge cases requiring human judgment and expertise

### Key Innovation: Human-in-the-Loop Pattern

This agent implements a sophisticated human-in-the-loop (HITL) pattern that recognizes when automated systems reach their limits. It provides a Gradio-based web UI where human experts can:
- View complete diagnostic histories
- Review escalated cases with full context
- Provide expert resolution guidance
- Handle edge cases that automated systems cannot resolve

## Two Primary Functions

### Function 1: Technician Appointment Scheduling

Automatically schedules in-home technician visits when diagnostics confirm hardware or infrastructure problems.

**Scheduling Criteria:**

**Scenario A: Local Outage with Equipment Issues**
- Customer has confirmed local outage (address-specific)
- Regional outage resolved but customer still affected
- Network reset attempted without success
- Modem/backend configuration shows signal problems
- Local pings failing or intermittent

**Scenario B: Complete Modem Failure**
- Modem completely offline (100% packet loss)
- No outages detected (local or regional)
- Abnormal LED status (not solid white)
- Backend pings to customer premises failing
- Suspected hardware failure

**Scenario C: Persistent Network Performance Issues**
- Consistent poor performance (20-40%+ packet loss)
- High latency (>50ms) despite network resets
- Multiple reset attempts without improvement
- Possible line quality or infrastructure problems

**Appointment Booking Process:**
1. Retrieves available technician slots from database
2. Determines priority (HIGH/MEDIUM/LOW) based on issue severity
3. Presents 3-5 available time slots to customer
4. Confirms booking with complete appointment details
5. Provides preparation instructions and service guarantee

**Example Appointment Confirmation:**
```
✅ TECHNICIAN APPOINTMENT CONFIRMED

Appointment ID: APT-20251104-00001
Customer: Sarah Johnson (CUST001)
Technician: Mike Johnson
Date: Tuesday, November 4, 2025
Time Window: 9:00 AM - 11:00 AM EST
Estimated Duration: 1-2 hours

Reason for Visit: Local outage confirmed with modem signal loss. 
Backend diagnostics show equipment needs physical inspection.

Equipment Bringing:
- Replacement modem
- Signal testing equipment
- Cable repair tools

Please Prepare:
✓ Ensure modem is accessible
✓ Have your account information ready
✓ Clear workspace around network equipment
✓ Someone 18+ must be home during visit

Technician will call you 30 minutes before arrival.
You can reschedule up to 24 hours before the appointment.

Service Guarantee: If our technician doesn't arrive within your 
time window, you'll receive a $20 account credit.
```

### Function 2: Human Expert Escalation (Human-in-the-Loop)

Recognizes when automated diagnostics cannot resolve customer issues and escalates to human experts.

**Escalation Scenarios:**

**Scenario 1: False Alarm - All Systems Normal**
- ✅ All diagnostics pass (modem, network, plan, outages)
- ✅ 0% packet loss, excellent ping results
- ✅ Solid white LED (functional modem)
- ❌ Customer still reports no internet access

**Why Human Needed:** Potential device-specific issues, DNS problems, WiFi credentials, VPN conflicts, ISP routing issues not visible to standard diagnostics.

**Scenario 2: Billing/Account Status Issues**
- Service suspension for non-payment
- Disputed charges affecting service
- Account status changes requiring manual review

**Why Human Needed:** Requires access to sensitive billing data and authority to make payment arrangements.

**Scenario 3: Complex Technical Edge Cases**
- IPv6 configuration problems
- CGNAT or port forwarding issues
- Business-class service requirements
- ISP infrastructure problems

**Why Human Needed:** Requires specialized networking expertise beyond standard troubleshooting.

**Human Escalation Format:**

When escalation is triggered, the agent outputs:
```
HUMAN_ESCALATION_REQUIRED

📋 ESCALATION SUMMARY - HELP-20251103-00234

Customer: Michael Chen (CUST002)
Issue: Customer reports complete inability to access internet 
despite all diagnostics showing normal operation.

🔍 COMPLETE DIAGNOSTIC HISTORY:

✅ Authentication Agent: Customer verified successfully
✅ Outage Check Agent: No local or regional outages
✅ Modem Check Agent: 
   - LED Status: Solid white (fully functional)
   - Backend Config: All systems normal
   - Signal strength: Excellent (-3 dBmV)
✅ Internet Plan Agent:
   - Plan: Contoso Ignite 500 (active)
   - Billing: All payments current
✅ Network Performance Agent:
   - Modem Ping: 0% packet loss, 2ms latency
   - All devices showing online
   - Network quality: Excellent

❌ CUSTOMER COMPLAINT: "I cannot load any websites or access 
email. Everything says 'No Internet Connection' even though 
WiFi shows connected."

🤔 WHY HUMAN ESCALATION REQUIRED:
All automated diagnostics indicate full functionality, but 
customer experience contradicts this. Suggests:
- Device-specific DNS or configuration issue
- Browser/app cache problems
- Customer connected to wrong network
- ISP-level routing issue not visible to diagnostics
- VPN or proxy interference

💡 RECOMMENDED NEXT STEPS FOR HUMAN AGENT:
1. Verify customer on correct WiFi network
2. Test on multiple devices
3. Try direct ethernet connection
4. Test specific websites to isolate DNS issues
5. Check DNS settings - try 8.8.8.8
6. Clear browser cache, try incognito mode
7. Disable VPN if active
8. Check parental controls or MAC filtering

📞 ESCALATION CONTACT:
Ticket ID: HELP-20251103-00234
Priority: Medium
Routing: Advanced Technical Support
```

The human expert then uses the Gradio UI to review this information and provide resolution guidance.

## Dispatch Database

The agent uses `documents/dispatch_database.json` containing:

**Technician Availability:**
- 7-day schedule with 2-hour time windows
- Morning (9-11am, 11am-1pm) and afternoon (1-3pm, 3-5pm) slots
- Saturday availability (reduced hours)
- Three technicians: Mike Johnson, Sarah Chen, David Martinez

**Appointment Scenarios:**
- CUST001: Local outage with modem issue (HIGH priority)
- CUST003: Modem offline, no outage (HIGH priority)
- CUST004: Poor network performance (MEDIUM priority)

**Helpdesk Scenarios:**
- False alarm: All checks pass but customer reports issues
- Billing suspension: Payment/account problems
- Complex technical: IPv6, CGNAT, infrastructure issues

**Sample Available Slots:**
- Tuesday, Nov 4: 9-11am (Mike Johnson), 11am-1pm (Sarah Chen), 3-5pm (Mike Johnson)
- Wednesday, Nov 5: 9-11am (Sarah Chen), 11am-1pm (David Martinez), 1-3pm (Mike Johnson)
- Thursday, Nov 6: All slots available
- Friday, Nov 7: 9-11am, 11am-1pm, 3-5pm available

## Human Expert UI

The agent includes a Gradio web interface for human experts to handle escalations.

**UI Features:**

1. **Pending Escalations Dashboard**
   - Real-time view of all pending cases
   - Full diagnostic context for each case
   - Context ID for tracking

2. **Response Interface**
   - Text input for expert guidance
   - Submit responses directly to customers
   - Response history tracking

3. **Quick Reference Guide**
   - Common false alarm resolutions
   - Billing issue procedures
   - Complex technical escalation paths

**Accessing the UI:**
- Default URL: `http://127.0.0.1:8086`
- Automatically launches when agent starts with `--enable-ui` flag
- No authentication required (assumes secure internal network)

**Using the UI:**
1. View pending escalations in left panel
2. Copy Context ID from escalation
3. Enter Context ID in response form
4. Write expert resolution guidance
5. Click "Send Response" to deliver to customer

## Agent Instructions

The agent follows this decision flow:

```
1. Review Complete Diagnostics
   └─ Authentication ✓
   └─ Outage Check ✓
   └─ Modem Check ✓
   └─ Internet Plan ✓
   └─ Network Performance ✓

2. Analyze Diagnostic Results
   ├─ Hardware/Infrastructure Issues Confirmed?
   │  ├─ YES → Schedule Technician
   │  └─ NO → Continue
   │
   ├─ All Diagnostics Pass But Customer Reports Issues?
   │  ├─ YES → Human Escalation (False Alarm)
   │  └─ NO → Continue
   │
   ├─ Billing/Account Issues Suspected?
   │  ├─ YES → Human Escalation (Billing)
   │  └─ NO → Continue
   │
   └─ Complex Technical Edge Case?
      ├─ YES → Human Escalation (Technical)
      └─ NO → SUCCESS (Issue Resolved)
```

## Workflow Integration

The Technical Dispatch Agent is the final step in the Contoso troubleshooting workflow:

```
Customer → Authentication → Outage Check → Video Request (parallel)
                                              ↓
                              ┌───────────────┼───────────────┐
                              ↓               ↓               ↓
                        Modem Check    Internet Plan   Network Performance
                              ↓               ↓               ↓
                              └───────────────┼───────────────┘
                                              ↓
                                    Technical Dispatch
                              ↓               ↓               ↓
                        Appointment    Human Expert    Issue Resolved
                        Scheduled      Escalation
```

**Inputs from Previous Agents:**
- Customer identity and account details
- Outage status (local and regional)
- Modem LED analysis and backend config
- Plan status, billing, data usage
- Network performance metrics, ping results

**Outputs:**
- Technician appointment confirmation with all details
- Human escalation request with complete diagnostic context
- Resolution confirmation if all checks passed

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Azure AI Foundry
AZURE_AI_PROJECTS_CONNECTION_STRING=your_connection_string
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Server Configuration
HOST=127.0.0.1
PORT=8106
UI_PORT=8086
HOST_AGENT_URL=http://localhost:12000
```

### Port Assignments

- **A2A Server**: Port 8106 (agent-to-agent communication)
- **Human Expert UI**: Port 8086 (Gradio web interface)

## Installation

1. Install dependencies:
```bash
pip install -e .
```

2. Configure environment variables in `.env`

3. Run the agent with UI:
```bash
python -m Contoso_agents.technical_dispatch_agent --enable-ui
```

Or run in A2A-only mode (no UI):
```bash
python -m Contoso_agents.technical_dispatch_agent --no-enable-ui
```

Custom configuration:
```bash
python -m Contoso_agents.technical_dispatch_agent \
  --host 127.0.0.1 \
  --port 8106 \
  --ui-port 8086 \
  --host-agent-url http://localhost:12000 \
  --enable-ui
```

## Self-Registration

The agent automatically registers with the host agent at `http://localhost:12000` on startup, providing:
- Agent name: "Contoso Technical Dispatch Agent"
- Agent URL: `http://127.0.0.1:8106`
- Capabilities: Appointment scheduling, human-in-the-loop escalation, comprehensive diagnostic integration

## Usage Examples

### Example 1: Scheduling Technician Appointment

**Request:**
```json
{
  "task": "Based on complete diagnostics, determine appropriate action. Customer CUST003 has modem completely offline (100% packet loss), no LED lights, no local or regional outages. All network reset attempts failed.",
  "context": {
    "customer_id": "CUST003",
    "diagnostic_summary": {
      "authentication": "verified",
      "outage_check": "no_outages",
      "modem_check": "offline_no_lights",
      "internet_plan": "active_paid",
      "network_performance": "modem_unreachable"
    }
  }
}
```

**Response:**
```
✅ TECHNICIAN APPOINTMENT CONFIRMED

Appointment ID: APT-20251105-00012
Customer: Emily Martinez (CUST003)
Technician: David Martinez
Date: Wednesday, November 5, 2025
Time Window: 11:00 AM - 1:00 PM EST
Estimated Duration: 1-2 hours
Priority: HIGH

Reason for Visit: Modem completely offline with 100% packet loss. 
No power or connectivity detected. Hardware replacement likely needed.

Equipment Bringing:
- Replacement modem
- Power supply tester
- Ethernet cables

Please Prepare:
✓ Ensure modem location is accessible
✓ Have account information ready
✓ Note any recent power events or physical damage
✓ Someone 18+ must be present during visit

Our technician will contact you 30 minutes before arrival.
You can reschedule up to 24 hours in advance.

Service Guarantee: $20 credit if technician doesn't arrive 
within scheduled window.
```

### Example 2: Human Expert Escalation

**Request:**
```json
{
  "task": "All diagnostics show perfect operation but customer insists they cannot access internet. Determine next steps.",
  "context": {
    "customer_id": "CUST002",
    "diagnostic_summary": {
      "authentication": "verified",
      "outage_check": "no_outages",
      "modem_check": "solid_white_led_excellent_signal",
      "internet_plan": "active_all_bills_paid",
      "network_performance": "0_packet_loss_excellent_pings"
    },
    "customer_complaint": "Cannot load any websites, email not working, shows 'No Internet Connection'"
  }
}
```

**Response:**
```
HUMAN_ESCALATION_REQUIRED

[Complete escalation summary as shown in examples above]
```

Human expert then uses the Gradio UI (port 8086) to:
1. Review the escalation with full diagnostic context
2. Enter Context ID from the escalation
3. Provide resolution: "I've reviewed your complete diagnostics..."
4. Submit response which is delivered back to customer

## Architecture

```
technical_dispatch_agent/
├── foundry_agent.py               # Core agent with HITL logic
├── foundry_agent_executor.py      # A2A executor with escalation support
├── __main__.py                    # Entry point with Gradio UI
├── pyproject.toml                 # Dependencies (includes gradio)
├── .env.example                   # Configuration template
├── README.md                      # This file
├── documents/
│   └── dispatch_database.json     # Appointment + escalation data
└── utils/
    ├── __init__.py
    └── self_registration.py       # Host agent registration
```

## Dependencies

- `a2a-sdk>=0.2.6`: Agent-to-Agent communication framework
- `azure-ai-agents>=1.1.0b2`: Azure AI Foundry agents
- `azure-ai-projects>=1.0.0b12`: Azure AI Projects SDK
- `azure-identity>=1.19.0`: Azure authentication
- `starlette>=0.41.0`: ASGI framework
- `uvicorn>=0.34.0`: ASGI server
- `gradio>=4.0.0`: **Human expert UI framework**

## Human-in-the-Loop Best Practices

### When to Escalate
- All automated checks pass but customer experience doesn't match
- Requires access to sensitive billing/account data
- Needs specialized expertise beyond standard troubleshooting
- Complex judgment calls about service credits or exceptions

### What NOT to Escalate
- Issues clearly resolved by network resets
- Confirmed hardware failures (schedule technician instead)
- Standard billing inquiries visible to automated systems
- Issues with clear diagnostic patterns

### Writing Effective Escalation Summaries
✅ **DO:**
- Include complete diagnostic history
- Provide specific test results and metrics
- Explain why human expertise is needed
- List recommended troubleshooting steps
- Include customer's exact complaint

❌ **DON'T:**
- Escalate without trying automated solutions first
- Omit diagnostic context
- Use vague language ("something's wrong")
- Skip recommended next steps

### Responding to Escalations (Human Experts)
✅ **DO:**
- Review complete diagnostic history before responding
- Reference specific metrics in your guidance
- Provide step-by-step instructions
- Confirm if issue requires technician visit
- Be empathetic and professional

❌ **DON'T:**
- Repeat checks already performed
- Ignore diagnostic data
- Make promises about issues outside your control
- Use technical jargon with customers

## Troubleshooting

**Agent fails to start:**
- Verify `AZURE_AI_PROJECTS_CONNECTION_STRING` is set
- Ensure port 8106 (A2A) and 8086 (UI) are not in use
- Check that host agent is running on port 12000

**UI not accessible:**
- Verify `--enable-ui` flag is set
- Check UI_PORT is not blocked by firewall
- Ensure gradio package is installed
- Try accessing `http://127.0.0.1:8086` directly

**Escalations not appearing in UI:**
- Check executor_instance is initialized
- Verify HUMAN_ESCALATION_REQUIRED is in agent response
- Review logs for escalation tracking messages
- Refresh status in UI

**Human response not delivered:**
- Verify correct Context ID entered
- Check that escalation is still pending
- Review logs for send_human_response errors
- Ensure executor has access to pending escalations

## Integration Notes

This agent completes the Contoso troubleshooting workflow and makes the final decision on customer issues. It seamlessly integrates diagnostic data from all five previous agents and provides two clear resolution paths:

1. **Automated Resolution**: Technician appointment scheduling for confirmed hardware issues
2. **Human-Assisted Resolution**: Expert escalation for complex edge cases

The human-in-the-loop pattern ensures that no customer is left without resolution when automated systems reach their limits, while the appointment scheduling capability ensures hardware issues are addressed promptly with minimal customer friction.

## Future Enhancements

- **Authentication for UI**: Add user authentication for human expert console
- **Escalation Analytics**: Track escalation patterns and resolution times
- **Appointment Rescheduling**: Allow customers to reschedule via agent
- **Technician Feedback Loop**: Capture post-visit reports to improve diagnostics
- **Escalation Prioritization**: Implement queue system for high-priority cases
- **Multi-Expert Support**: Allow multiple human experts to handle escalations concurrently
