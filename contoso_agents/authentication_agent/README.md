# Contoso Authentication Agent

This agent handles customer authentication for the Contoso support system.

## Features
- Verifies customer identity using:
  - First Name
  - Last Name  
  - Postal Code
  - Date of Birth
- Searches customer database for matching records
- Provides customer details upon successful authentication

## Setup

1. Copy `.env.example` to `.env` and fill in your Azure credentials
2. Install dependencies: `pip install -r requirements.txt` or use `uv`
3. Run the agent: `python __main__.py`

## Configuration

Default port: 8101
Configure in `.env` file or via environment variables.
