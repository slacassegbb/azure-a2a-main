# Port Allocation

Existing agent port assignments. New agents must not conflict.

## Infrastructure
| Port | Service |
|------|---------|
| 12000 | Host Agent (backend) |

## Remote Agents
| Port | Agent |
|------|-------|
| 8001 | Classification Triage |
| 8006 | Legal Compliance |
| 8015 | Twilio |
| 8016 | Twilio2 |
| 8020 | QuickBooks |
| 8021 | Teams |
| 9001 | Claims Specialist |
| 9002 | Branding & Content |
| 9004 | Fraud Intelligence |
| 9010 | Image Generator |
| 9020 | Email / Template |
| 9030 | Stripe |
| 9035 | GitHub |
| 9036 | PowerPoint |
| 9037 | Excel |
| 9038 | Word |

## Available Ranges
- 8022-8099 (legacy range)
- 9039-9099 (modern range)

## Gradio UI Ports
Convention: A2A_PORT + 65 or use 8085 default.
