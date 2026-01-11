# Contoso Outage Check Agent

This agent checks for internet service outages affecting Contoso customers.

## Features
- Checks local outages (address-specific)
- Checks regional outages if no local outage found
- Provides detailed outage information including:
  - Outage type and status
  - Affected services
  - Cause and estimated resolution
  - Number of affected customers
  - Latest updates

## Setup

1. Copy `.env.example` to `.env` and fill in your Azure credentials
2. Install dependencies: `pip install -r requirements.txt` or use `uv`
3. Run the agent: `python __main__.py`

## Configuration

Default port: 8102
Configure in `.env` file or via environment variables.
