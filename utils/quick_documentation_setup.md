cd backend
source venv/bin/activate
python -m pip install -r requirements.txt
python bckend_production.py

cd frontend
npm install
npm run dev

for file processing:
brew install --cask libreoffice

ngrok: (need hobby account)
ngrok http 8005 --domain=agent1.ngrok.app 
ngrok config add-authtoken 2z8qrIZfW6CCnGGwIUpRbXkB1Gi_2Fpc73dZABNRG7ewSC7ap

Remote Agents:
python3 -m venv .venv
source .venv/bin/activate
pip install uv
uv run .

Mask-assisted refinement flow (frontend)
- Click “Refine this image” on any assistant image to activate refinement mode.
- Choose “Paint mask” to open the canvas editor, highlight the region to edit, and save the generated mask.
- The saved mask uploads automatically and is passed to the remote agent alongside the base image.
- Submit your prompt as usual; the backend enforces matching dimensions and routes both files via A2A.

Google ADK Agent:
python3 -m venv .venv
source .venv/bin/activate
pip install a2a-sdk
python __main__.py

Service Now Agent (MCP SERVER and NGROK, you don't need NGROK is your deploy the MCP server and host a ppublic IP address)

Create tunne to your localhost via NGROK (open terminal and run the following NGROK command) (you will need your own domain name for this): 

ngrok http 8005 --domain=agent1.ngrok.app

MCP Server Setup: (make sure you have a Service Now instance and set your. .env variables in the root directory of the MCP server folder)
cd /azurefoundry_SN/MCP_SERVICENOW/servicenow-mcp
python -m mcp_server_servicenow.cli --transport http --host 127.0.0.1 --port 8005

Launch the service now agent with UI

cd remote_agents/azurefoundry_SN
python3 -m venv .venv
source .venv/bin/activate
uv run . --ui (use the --ui to also load the gradio app on localhost, this agent has it's own UI interface)