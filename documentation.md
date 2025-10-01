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