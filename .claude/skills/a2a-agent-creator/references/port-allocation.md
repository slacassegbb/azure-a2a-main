# Port Allocation

Existing agent port assignments. New agents must not conflict.

## Infrastructure
| Port | Service |
|------|---------|
| 12000 | Host Agent (backend) |

## Remote Agents
| Port | Agent | Deployed |
|------|-------|----------|
| 8001 | Classification Triage | Yes |
| 8002 | Deep Search Knowledge | No |
| 8003 | Sentiment Analysis | No |
| 8004 | SalesForce CRM | No |
| 8005 | ServiceNow | No |
| 8006 | Legal Compliance | No |
| 8009 | Classification ResponseAPI | No |
| 8015 | Twilio | No |
| 8016 | Twilio2 | Yes |
| 8020 | QuickBooks | Yes |
| 8021 | Teams | Yes |
| 9001 | Claims Specialist | No |
| 9002 | Branding & Content | Yes |
| 9004 | Fraud Intelligence | No |
| 9010 | Image Generator | Yes |
| 9020 | Template | No |
| 9028 | Sora 2 Video Generator | Yes |
| 9029 | Email | Yes |
| 9030 | Stripe | Yes |
| 9032 | Reporter | No |
| 9035 | GitHub | No |
| 9036 | PowerPoint | No |
| 9037 | Excel | No |
| 9038 | Word | No |
| 9039 | Time Series | No |
| 9040 | Stock Market | No |
| 9041 | Google Maps | No |
| 9042 | HubSpot | Yes |
| 9043 | Assessment & Estimation | No |
| 9066 | Image Analysis | No |

## Available Ranges
- 8007-8008, 8010-8014, 8017-8019, 8022-8099 (legacy range)
- 9044-9065, 9067-9099 (modern range)

## Gradio UI Ports
Convention: A2A_PORT + 65 or use 8085 default.
