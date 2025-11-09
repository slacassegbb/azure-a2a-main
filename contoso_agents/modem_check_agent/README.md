# Contoso Modem Check Agent

This agent performs comprehensive modem diagnostics for Contoso customers.

## Features
- **LED Status Analysis**: Analyzes modem LED indicators (solid white, blinking white, blinking yellow, solid yellow, red, no light)
- **Backend Configuration Checks**: Reviews modem configuration in Contoso backend systems
- **Signal Strength Analysis**: Checks downstream power, upstream power, and SNR levels
- **Firmware Status**: Verifies firmware version and update status
- **Discrepancy Detection**: Identifies mismatches between visual LED status and backend data
- **Comprehensive Diagnostics**: Provides detailed diagnosis and recommendations

## LED Status Meanings
- **Solid White**: Live and functional ✅
- **Blinking White**: Looking for internet connectivity 🔄
- **Blinking Yellow**: Modem turning on/booting 🟡
- **Solid Yellow**: Connectivity issue ⚠️
- **Red**: Internal modem issue ❌
- **No Light**: Modem off or no power ⚫

## Setup

1. Copy `.env.example` to `.env` and fill in your Azure credentials
2. Install dependencies: `pip install -r requirements.txt` or use `uv`
3. Run the agent: `python __main__.py`

## Configuration

Default port: 8103
Configure in `.env` file or via environment variables.

## Usage

The agent accepts:
- Text descriptions of modem LED status
- Customer ID for backend configuration lookup
- Image/video of modem for visual analysis (future enhancement)
