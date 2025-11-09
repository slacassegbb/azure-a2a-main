# Contoso Network Performance Agent

Comprehensive network diagnostics agent for Contoso internet troubleshooting. Performs ping tests, device discovery, performance analysis, and proactive network resets.

## Overview

This agent is part of the Contoso Customer Service multi-agent system. It performs detailed network diagnostics to identify connectivity issues and recommend appropriate remediation actions.

### Key Capabilities

1. **Device Discovery**: Identifies all connected devices with names, IP addresses, MAC addresses, and types (laptops, phones, tablets, smart TVs, IoT devices)

2. **Ping Diagnostics**: 
   - Tests modem connectivity (192.168.1.1)
   - Tests network pod connectivity
   - Sample tests to connected devices
   - Measures latency and packet loss

3. **Performance Analysis**:
   - Evaluates overall network health
   - Identifies degraded performance patterns
   - Detects critical failures requiring technician dispatch

4. **Proactive Network Reset**:
   - Recommends resets even when performance appears normal (preventive maintenance)
   - Executes network resets for performance issues
   - Clears ARP cache, DHCP leases, DNS cache, and connection states

## Network Database

The agent uses `documents/network_database.json` containing:
- Network topology for 6 customer profiles (CUST001-CUST006)
- Modem status and IP addresses
- Network pod information with signal strength
- Complete device inventories with IPs and MAC addresses
- Ping test results with packet loss and latency metrics
- Performance status assessments

### Sample Network Scenarios

- **CUST001**: Excellent performance, 12 devices, 2 pods
- **CUST002**: Excellent performance, 8 devices, no pods
- **CUST003**: Critical failure, modem offline, 100% packet loss (requires technician)
- **CUST004**: Poor performance, 20-40% packet loss, high latency (network reset recommended)
- **CUST005**: Excellent performance, 9 devices, 1 pod
- **CUST006**: Excellent performance, 11 devices, no pods

## Agent Instructions

The agent follows this diagnostic protocol:

1. **Retrieve Network Data**: Fetch customer's network configuration using customer_id
2. **Modem Analysis**: Check modem ping responses, packet loss, latency
3. **Pod Diagnostics**: Evaluate network pod performance and signal strength
4. **Device Connectivity**: Review device ping results and identify patterns
5. **Device Inventory**: List all connected devices with names and IPs
6. **Status Determination**:
   - **Excellent** (0% loss, <10ms): Recommend proactive reset before all-clear
   - **Good** (0% loss, 10-30ms): Recommend proactive reset
   - **Poor** (10-40% loss or >30ms): Immediate network reset needed
   - **Critical** (>40% loss or modem offline): Technician dispatch required

### Proactive Network Reset Logic

**CRITICAL FEATURE**: Even when network performance appears normal, the agent recommends a proactive network reset as preventive maintenance. This prevents false negatives where tests pass but customers still experience issues.

**Reset Actions**:
- Clear ARP cache
- Reset DHCP leases
- Restart modem interface
- Restart network pods
- Clear DNS cache
- Reset connection states

**Expected Downtime**: 30-60 seconds

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Azure AI Foundry
AZURE_AI_PROJECTS_CONNECTION_STRING=your_connection_string
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o

# Server Configuration
HOST=127.0.0.1
PORT=8105
HOST_AGENT_URL=http://localhost:12000
```

### Port Assignment

This agent runs on **port 8105** by default.

## Installation

1. Install dependencies:
```bash
pip install -e .
```

2. Configure environment variables in `.env`

3. Run the agent:
```bash
python -m Contoso_agents.network_performance_agent
```

Or with custom settings:
```bash
python -m Contoso_agents.network_performance_agent --host 127.0.0.1 --port 8105 --host-agent-url http://localhost:12000
```

## Self-Registration

The agent automatically registers with the host agent at `http://localhost:12000` on startup, providing:
- Agent name: "Contoso Network Performance Agent"
- Agent URL: `http://127.0.0.1:8105`
- Capabilities: Network diagnostics, ping tests, device discovery, proactive network resets

## Usage in Workflow

The Network Performance Agent is typically invoked after:
1. Customer authentication successful
2. No service outages detected
3. Modem check completed

The agent provides critical diagnostics for the "No Internet Access" workflow, helping determine whether:
- A simple network reset will resolve the issue
- The customer's internet is actually working (false alarm)
- A technician visit is required for hardware/infrastructure problems

## Example Request

```json
{
  "task": "Perform comprehensive network diagnostics. List all connected devices with IPs, run ping tests to modem and pods, analyze network performance, and recommend whether network reset or technician dispatch is needed.",
  "context": {
    "customer_id": "CUST004"
  }
}
```

## Example Response

```
Network Diagnostic Report - Customer CUST004

Network Topology:
- Modem: 192.168.1.1 (DEGRADED)
- Network Name: Thompson_Home
- Total Devices: 15 (11 active)
- Network Pods: 2 (Upstairs Pod, Basement Pod)

Modem Ping Test:
- Target: 192.168.1.1
- Packets Sent: 10
- Packets Received: 8
- Packet Loss: 20%
- Average Latency: 45ms
- Status: POOR

Network Pod Results:
1. Upstairs Pod (192.168.1.2):
   - Packet Loss: 30%
   - Average Latency: 78ms
   - Status: POOR

2. Basement Pod (192.168.1.3):
   - Packet Loss: 40%
   - Average Latency: 120ms
   - Status: CRITICAL

Connected Devices:
1. David's Laptop - 192.168.1.130 - Online
2. David's Phone - 192.168.1.131 - Online
3. Home Office PC - 192.168.1.132 - Online
4. Smart TV 1 - 192.168.1.133 - Online
5. Smart TV 2 - 192.168.1.134 - Online
[... 6 more devices ...]

Performance Analysis:
- Issues Detected:
  * High packet loss (20-40%)
  * Elevated latency across all devices
  * Pod performance degraded
  * Intermittent connectivity

RECOMMENDATION: IMMEDIATE NETWORK RESET
I recommend performing a network reset to resolve these connectivity issues. This will clear the ARP cache, reset DHCP leases, restart the modem interface, restart network pods, clear DNS cache, and reset connection states. Expected downtime: 30-60 seconds.

After the reset, we should see packet loss drop to 0% and latency return to normal (<10ms).
```

## Integration with Host Agent

The host agent orchestrates the network performance check as part of the troubleshooting workflow. After receiving the diagnostic report, the host determines the next steps:
- Network reset recommended → Execute reset or guide customer
- Critical failure detected → Route to Technical Dispatch Agent for technician visit
- Performance excellent → Route to Technical Dispatch Agent to investigate other potential causes

## Dependencies

- `a2a-sdk>=0.2.6`: Agent-to-Agent communication framework
- `azure-ai-agents>=1.1.0b2`: Azure AI Foundry agents
- `azure-ai-projects>=1.0.0b12`: Azure AI Projects SDK
- `azure-identity>=1.19.0`: Azure authentication
- `starlette>=0.41.0`: ASGI framework
- `uvicorn>=0.34.0`: ASGI server

## Development

Run tests:
```bash
pip install -e ".[dev]"
pytest
```

## Architecture

```
network_performance_agent/
├── foundry_agent.py          # Core agent with Azure AI Foundry
├── foundry_agent_executor.py # A2A executor implementation
├── __main__.py               # Entry point with CLI
├── pyproject.toml            # Dependencies
├── .env.example              # Configuration template
├── README.md                 # This file
├── documents/
│   └── network_database.json # Network diagnostic data
└── utils/
    ├── __init__.py
    └── self_registration.py  # Host agent registration
```

## Troubleshooting

**Agent fails to start:**
- Verify `AZURE_AI_PROJECTS_CONNECTION_STRING` is set correctly
- Ensure port 8105 is not in use
- Check that host agent is running on port 12000

**Network diagnostics incomplete:**
- Verify customer_id exists in network_database.json
- Check Azure AI Foundry model deployment is accessible
- Review agent logs for vector store creation issues

**Self-registration fails:**
- Ensure host agent is running and accessible at the configured URL
- Check network connectivity to host agent
- Agent will continue running even if registration fails
