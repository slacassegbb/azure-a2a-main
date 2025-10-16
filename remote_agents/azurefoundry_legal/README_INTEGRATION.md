# AI Foundry Expert Agent - Integrated Citibank Dashboard

This is an integrated version that combines the original AI Foundry Expert Agent functionality with a new Citibank Support Dashboard UI.

## Features

### Original AI Foundry Functionality (Preserved)
- ✅ A2A server for agent-to-agent communication
- ✅ Background registration with host agents
- ✅ UI notifications for pending expert requests
- ✅ Azure AI Foundry integration
- ✅ ServiceNow, CitiBank, Web Search, and File Knowledge capabilities
- ✅ Expert consultation mode for human-in-the-loop scenarios

### New Citibank Dashboard UI (Added)
- ✅ Professional Citibank-branded interface
- ✅ Customer information display
- ✅ Account overview with balances
- ✅ ServiceNow ticket management
- ✅ Recent transaction history
- ✅ Agent tools and quick actions
- ✅ Knowledge base integration
- ✅ Escalation workflows

## Usage

### Running with UI (Recommended)
```bash
python __main__.py --ui --ui-port 8085
```

### Running A2A Server Only
```bash
python __main__.py --port 8000
```

### Running with Custom Ports
```bash
python __main__.py --ui --host 0.0.0.0 --port 8000 --ui-port 8085
```

## UI Features

### Dashboard Layout
1. **Header**: Citibank branding with agent status and connection info
2. **Status Bar**: Real-time notifications for pending host agent requests
3. **Left Panel**: Customer information and account overview
4. **Center Panel**: Chat interface for agent interactions
5. **Bottom Panel**: ServiceNow tickets and transaction history
6. **Tools Panel**: Agent utilities and data refresh

### Chat Functionality
The chat interface intelligently routes queries:
- **Dashboard Keywords**: Routes to Citibank dashboard responses (tickets, accounts, etc.)
- **AI Foundry Keywords**: Routes to Azure AI Foundry agent for complex queries
- **Pending Requests**: Handles expert consultation requests from host agents

### Quick Commands
- 🎫 View Tickets: Show all open ServiceNow tickets
- 💰 Account Summary: Display customer account overview
- 🔺 Escalate: Show escalation options and procedures
- 📋 Knowledge Base: Access agent knowledge base

## Environment Variables Required

```bash
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=your_endpoint_here
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=your_deployment_name_here
```

## Dependencies

The integration adds `pandas>=2.0.0` to the existing dependencies for data table formatting.

## Architecture

### Preserved Components
- `create_a2a_server()`: A2A server creation
- `run_a2a_server_in_thread()`: Background server execution
- `register_agent_with_host()`: Host agent registration
- `get_foundry_response()`: Original AI Foundry chat handler
- `check_pending_requests()`: UI notification system

### New Components
- `CitibankSupportDashboard`: Dashboard data and logic
- `format_customer_info()`: Customer data formatting
- `format_accounts_table()`: Account table formatting
- `format_tickets_table()`: Ticket table formatting
- `format_transactions_table()`: Transaction table formatting
- `chat_response()`: Integrated chat handler

### Integration Points
- **Unified Chat Interface**: Single chat that routes to appropriate handler
- **Shared Agent Instance**: Uses the same AI Foundry agent instance for consistency
- **Preserved Notifications**: All original UI notifications work with new dashboard
- **Background Services**: A2A server and registration run in background

## File Structure

```
azurefoundry_SN/
├── __main__.py              # Integrated main file
├── test_ui.py              # Original dashboard (reference)
├── foundry_agent_executor.py # AI Foundry integration
├── pyproject.toml          # Updated dependencies
├── Citi_logo.png          # Citibank branding
└── README_INTEGRATION.md  # This file
```

## Troubleshooting

### Common Issues
1. **Missing Dependencies**: Run `pip install pandas` if not installed
2. **Environment Variables**: Ensure Azure AI Foundry credentials are set
3. **Port Conflicts**: Use different ports if 8000/8085 are occupied
4. **Logo Not Loading**: Ensure `Citi_logo.png` is in the same directory

### Debug Mode
For debugging, check the console output for:
- A2A server startup messages
- Agent registration status
- Chat routing decisions
- Error messages and stack traces

## Future Enhancements

Potential improvements:
- Real-time data updates from ServiceNow
- Integration with actual CitiBank APIs
- Enhanced customer data management
- Additional agent tools and workflows
- Mobile-responsive design
- Multi-language support 