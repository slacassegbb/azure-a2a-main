# Contoso Internet Plan Agent

This agent manages internet plan verification, data usage monitoring, and billing status checks.

## Features
- **Plan Details**: Reviews customer plan type, speeds, data limits, and costs
- **Data Usage Monitoring**: 
  - Tracks current usage against plan limits
  - Calculates overages and associated charges
  - Reports days until billing cycle renewal
- **Billing Status**: 
  - Checks last 3 bills payment status
  - Identifies service shutoff risk from unpaid bills
  - Reviews payment history
- **Access Determination**: Determines if customer should have active internet access

## Key Capabilities
✅ Unlimited plan verification  
⚠️ Data limit overage detection and charge calculation  
❌ Unpaid bill detection (service shutoff risk)  
📊 Complete billing history analysis

## Synthetic Data
Includes 6 customer profiles:
- 5 customers with unlimited plans
- **CUST004** with limited 500GB plan who has exceeded by 20GB with billing cycle renewing in 3 days

## Setup

1. Copy `.env.example` to `.env` and fill in your Azure credentials
2. Install dependencies: `pip install -r requirements.txt` or use `uv`
3. Run the agent: `python __main__.py`

## Configuration

Default port: 8104
Configure in `.env` file or via environment variables.

## Usage

The agent integrates with the multi-agent workflow to:
- Verify customer has paid internet service
- Check for data limit issues
- Determine if connectivity problems are billing-related
