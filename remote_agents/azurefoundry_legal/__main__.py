import asyncio
import logging
import os
import traceback
import threading
import json
import datetime
import re
from typing import Dict, List, Tuple, Optional
import pandas as pd

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_legal_agent_executor, initialize_foundry_legal_agents_at_startup, FoundryLegalAgentExecutor
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler 
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

load_dotenv()

# Configure logging - hide verbose Azure SDK logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Silence verbose Azure SDK HTTP logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)


def _normalize_env_value(raw_value: str | None) -> str:
    if raw_value is None:
        return ''
    return raw_value.strip()


def _resolve_default_host() -> str:
    value = _normalize_env_value(os.getenv('A2A_ENDPOINT'))
    return value or 'localhost'


def _resolve_default_port() -> int:
    raw_port = _normalize_env_value(os.getenv('A2A_PORT'))
    if raw_port:
        try:
            return int(raw_port)
        except ValueError:
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 8006", raw_port)
    return 8006


def resolve_agent_url(bind_host: str, bind_port: int) -> str:
    endpoint = _normalize_env_value(os.getenv('A2A_ENDPOINT'))
    if endpoint:
        if endpoint.startswith(('http://', 'https://')):
            return endpoint.rstrip('/') + '/'
        host_for_url = endpoint
    else:
        host_for_url = bind_host if bind_host != "0.0.0.0" else _resolve_default_host()

    return f"http://{host_for_url}:{bind_port}/"

# Import self-registration utility
try:
    from utils.self_registration import register_with_host_agent, get_host_agent_url
    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError:
    # Fallback if utils not available
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    def get_host_agent_url() -> str:
        return ""
    SELF_REGISTRATION_AVAILABLE = False

DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()  # Changed to avoid conflict with other agents
DEFAULT_UI_PORT = 8095  # Changed to avoid conflict with other agents

# Global reference to the agent executor to check for pending tasks
HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())
agent_executor_instance = None


class LegalComplianceDashboard:
    def __init__(self):
        # GDPR compliance case data (default)
        self.gdpr_compliance_case = {
            "case_id": "GDPR-2025-001",
            "client_name": "TechCorp International",
            "contact": "Sarah Johnson, General Counsel",
            "email": "sarah.johnson@techcorp.com",
            "phone": "+1 (555) 987-6543",
            "case_type": "GDPR Compliance Assessment",
            "priority": "High",
            "status": "In Progress",
            "assigned_attorney": "Michael Rodriguez",
            "last_updated": "January 27, 2025 - 3:15 PM EST",
            "compliance_deadline": "March 15, 2025"
        }
        
        # SOX audit case data (for complex compliance)
        self.sox_audit_case = {
            "case_id": "SOX-2025-002",
            "client_name": "Financial Services Inc.",
            "contact": "David Chen, CFO",
            "email": "david.chen@financialservices.com",
            "phone": "+1 (555) 456-7890",
            "case_type": "SOX Section 404 Audit",
            "priority": "Critical",
            "status": "Under Review",
            "assigned_attorney": "Jennifer Williams",
            "last_updated": "January 27, 2025 - 1:30 PM EST",
            "compliance_deadline": "February 28, 2025"
        }
        
        # Set default case to GDPR compliance
        self.current_case = self.gdpr_compliance_case
        
        # Add missing attributes for dashboard data
        self.recent_transactions = []
        self.accounts = []
        self.open_tickets = []
        self.agent_knowledge = {
            "login_issues": {"solution": "Contact IT support for login assistance"},
            "credit_limit": {"solution": "Contact credit department for limit increase"}
        }
        
        # Ana Lucia account information (default)
        self.ana_lucia_accounts = [
            {
                "account_type": "Checking",
                "account_number": "****4881",
                "balance": "R$24,750.30",
                "status": "Active",
                "last_transaction": "Jul 1, 2025"
            },
            {
                "account_type": "Savings",
                "account_number": "****2001",
                "balance": "R$87,450.12",
                "status": "Active", 
                "last_transaction": "Jun 28, 2025"
            },
            {
                "account_type": "Credit Card",
                "account_number": "****5887",
                "balance": "R$3,240.10",
                "status": "Active",
                "last_transaction": "Jul 2, 2025"
            }
        ]
        
        # Set default accounts to Ana Lucia
        self.accounts = self.ana_lucia_accounts
        
        # Open tickets
        self.open_tickets = [
            {
                "ticket_id": "INC0012345",
                "priority": "High",
                "status": "In Progress",
                "subject": "Unable to access online banking",
                "created": "Jan 15, 2024 09:30 AM",
                "assigned_to": "Digital Banking Team",
                "last_update": "Jan 15, 2024 02:15 PM",
                "description": "Customer reports authentication errors when trying to log into online banking platform",
                "resolution_time": "4 hours"
            },
            {
                "ticket_id": "REQ0067890", 
                "priority": "Medium",
                "status": "Pending Approval",
                "subject": "Credit limit increase request",
                "created": "Jan 14, 2024 11:20 AM",
                "assigned_to": "Credit Operations",
                "last_update": "Jan 15, 2024 10:45 AM",
                "description": "Customer requesting credit limit increase from $5,000 to $10,000",
                "resolution_time": "24 hours"
            }
        ]
        
        # Recent transactions
        self.recent_transactions = [
            {"date": "Jan 15, 2024", "description": "Amazon Purchase", "amount": "-$89.99", "account": "****1234"},
            {"date": "Jan 15, 2024", "description": "Salary Deposit", "amount": "+$3,200.00", "account": "****1234"},
            {"date": "Jan 14, 2024", "description": "Starbucks", "amount": "-$5.67", "account": "****9012"},
            {"date": "Jan 14, 2024", "description": "Gas Station", "amount": "-$45.20", "account": "****9012"},
            {"date": "Jan 13, 2024", "description": "Transfer to Savings", "amount": "-$500.00", "account": "****1234"}
        ]
        
        # Knowledge base for agent responses
        self.agent_knowledge = {
            "login_issues": {
                "solution": """**Login Issue Resolution Steps:**
1. Verify customer identity (completed ✓)
2. Check account status - Active ✓
3. Reset password through secure channel
4. Clear browser cache/cookies
5. Try incognito/private browsing mode
6. If issue persists, escalate to Digital Banking Team

**Common Causes:**
- Browser compatibility issues
- Cached credentials
- Recent password policy changes
- Account security flags

**Next Actions:**
- Send password reset link to registered email
- Create follow-up task for 24 hours
- Document resolution in Salesforce""",
                
                "escalation": "Digital Banking Team - Level 2 Support",
                "sla": "4 hours for High priority login issues"
            },
            
            "credit_limit": {
                "solution": """**Credit Limit Increase Process:**
1. Verify customer identity and account standing ✓
2. Review credit history and payment patterns
3. Check current utilization ratio: 46.8%
4. Assess income verification requirements
5. Submit to Credit Operations for approval

**Current Status:**
- Account in good standing ✓
- No recent late payments ✓
- Income verification required
- Approval pending manager review

**Next Actions:**
- Request recent pay stubs
- Schedule callback within 24 hours
- Update customer on approval timeline""",
                
                "escalation": "Credit Operations Manager",
                "sla": "24-48 hours for credit decisions"
            }
        }

    def switch_to_sox_audit(self):
        """Switch to SOX audit case for complex compliance"""
        self.current_case = self.sox_audit_case
    
    def switch_to_gdpr_compliance(self):
        """Switch back to GDPR compliance case (default)"""
        self.current_case = self.gdpr_compliance_case
    
    def get_case_analytics(self):
        """Get case analytics based on current legal case"""
        if self.current_case == self.gdpr_compliance_case:
            return """
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #1e3a8a; margin: 0 0 10px 0;">⚖️ Case Status & Metrics</h4>
                <p><strong>Case Status:</strong> ✅ In Progress</p>
                <p><strong>Priority Level:</strong> High</p>
                <p><strong>Compliance Score:</strong> 85%</p>
                <p><strong>Risk Assessment:</strong> Medium</p>
                <p><strong>Deadline:</strong> March 15, 2025</p>
            </div>
            
            <div style="background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #0369a1; margin: 0 0 10px 0;">📋 Compliance Requirements</h4>
                <p>✅ <strong>Data Processing Inventory</strong> - Complete</p>
                <p>✅ <strong>Privacy Policy Review</strong> - Updated</p>
                <p>✅ <strong>Data Subject Rights</strong> - Implemented</p>
                <p>⚠️ <strong>Data Retention Policy</strong> - Needs Update</p>
                <p>⚠️ <strong>Cross-Border Transfers</strong> - Under Review</p>
            </div>
            
            <div style="background: #f0fdf4; border: 1px solid #22c55e; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #15803d; margin: 0 0 10px 0;">🎯 Recommended Actions</h4>
                <p>🔹 <strong>Update Data Retention Policy</strong> - Align with GDPR</p>
                <p>🔹 <strong>Review Cross-Border Transfers</strong> - SCCs needed</p>
                <p>🔹 <strong>Conduct DPIA</strong> - High-risk processing</p>
                <p>🔹 <strong>Staff Training</strong> - GDPR awareness</p>
                <p>🔹 <strong>Incident Response Plan</strong> - 72-hour notification</p>
            </div>
            
            <div style="background: #fefce8; border: 1px solid #eab308; border-radius: 8px; padding: 15px;">
                <h4 style="color: #a16207; margin: 0 0 10px 0;">📈 Compliance Insights</h4>
                <p><strong>Data Processing Activities:</strong> 15 identified</p>
                <p><strong>Data Subject Requests:</strong> 3 pending</p>
                <p><strong>Breach Incidents:</strong> 0 in last 12 months</p>
                <p><strong>Audit Findings:</strong> 2 minor issues</p>
                <p><strong>Training Completion:</strong> 75% of staff</p>
            </div>
            """
        else:  # SOX Audit Case
            return """
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #1e3a8a; margin: 0 0 10px 0;">⚖️ Audit Status & Metrics</h4>
                <p><strong>Audit Status:</strong> ⚠️ Under Review</p>
                <p><strong>Priority Level:</strong> Critical</p>
                <p><strong>Compliance Score:</strong> 92%</p>
                <p><strong>Risk Assessment:</strong> Low</p>
                <p><strong>Deadline:</strong> February 28, 2025</p>
            </div>  
            
            <div style="background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #0369a1; margin: 0 0 10px 0;">📋 SOX Controls Assessment</h4>
                <p>✅ <strong>User Access Review</strong> - Quarterly completed</p>
                <p>✅ <strong>Change Management</strong> - CAB process followed</p>
                <p>✅ <strong>Logging & Retention</strong> - 7-year retention</p>
                <p>✅ <strong>Financial Controls</strong> - Section 404 compliant</p>
                <p>⚠️ <strong>System Documentation</strong> - Minor updates needed</p>
            </div>
            
            <div style="background: #f0fdf4; border: 1px solid #22c55e; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #15803d; margin: 0 0 10px 0;">🎯 Audit Recommendations</h4>
                <p>🔹 <strong>Update Control Narratives</strong> - System changes</p>
                <p>🔹 <strong>Enhance Monitoring</strong> - Real-time alerts</p>
                <p>🔹 <strong>Staff Training</strong> - SOX awareness</p>
                <p>🔹 <strong>Documentation Review</strong> - Policy updates</p>
                <p>🔹 <strong>Testing Procedures</strong> - Control effectiveness</p>
            </div>
            
            <div style="background: #fefce8; border: 1px solid #eab308; border-radius: 8px; padding: 15px;">
                <h4 style="color: #a16207; margin: 0 0 10px 0;">📈 Audit Insights</h4>
                <p><strong>Control Tests:</strong> 45 completed</p>
                <p><strong>Deficiencies Found:</strong> 2 minor</p>
                <p><strong>Remediation Actions:</strong> 1 pending</p>
                <p><strong>Management Attestations:</strong> All signed</p>
                <p><strong>External Audit:</strong> KPMG Q2 2025</p>
            </div>
            """
    
    def get_dashboard_data(self):
        """Return all dashboard data for display"""
        return {
            "case": self.current_case,
            "accounts": self.accounts,
            "tickets": self.open_tickets,
            "transactions": self.recent_transactions,
            "analytics": self.get_case_analytics()
        }

    def process_agent_query(self, query: str) -> str:
        """Process agent queries and provide relevant information"""
        query_lower = query.lower()
        
        # Check for ticket references
        ticket_pattern = r'(INC|REQ|CHG|PRB)\d{7}'
        ticket_match = re.search(ticket_pattern, query.upper())
        
        if ticket_match:
            ticket_id = ticket_match.group()
            return self.get_ticket_details(ticket_id)
        
        # Knowledge base responses
        if any(word in query_lower for word in ["login", "password", "access", "authentication"]):
            return self.agent_knowledge["login_issues"]["solution"]
        
        elif any(word in query_lower for word in ["credit", "limit", "increase"]):
            return self.agent_knowledge["credit_limit"]["solution"]
        
        elif any(word in query_lower for word in ["account", "balance", "transaction"]):
            return self.get_account_summary()
        
        elif any(word in query_lower for word in ["escalate", "manager", "supervisor"]):
            return self.get_escalation_options()
        
        else:
            return self.get_general_agent_response()

    def get_ticket_details(self, ticket_id: str) -> str:
        """Get detailed information about a specific ticket"""
        for ticket in self.open_tickets:
            if ticket["ticket_id"] == ticket_id:
                return f"""**🎫 Ticket Details: {ticket_id}**

**Priority**: {ticket['priority']} | **Status**: {ticket['status']}
**Subject**: {ticket['subject']}
**Created**: {ticket['created']}
**Assigned To**: {ticket['assigned_to']}
**Last Update**: {ticket['last_update']}
**Target Resolution**: {ticket['resolution_time']}

**Description**: {ticket['description']}

**Agent Actions Available:**
- Update ticket status
- Add internal notes
- Escalate to supervisor
- Schedule customer callback
- Close ticket with resolution

**Customer Communication:**
- Last contacted: {ticket['last_update']}
- Preferred contact: Email
- Next follow-up: Within 2 hours"""
        
        return f"❌ Ticket {ticket_id} not found in current customer's open tickets."

    def get_account_summary(self) -> str:
        """Provide case summary for legal agent"""
        case_name = self.current_case.get('name', 'Unknown Case')
        case_type = self.current_case.get('type', 'Compliance')
        risk_level = self.current_case.get('risk_level', 'Medium')
        
        return f"""**⚖️ Case Summary for {case_name}**

**Case Type**: {case_type}
**Risk Level**: {risk_level}
**Status**: Active Investigation

**Case Details:**
• **Case ID**: {self.current_case.get('case_id', 'CASE-001')}
• **Priority**: {self.current_case.get('priority', 'High')}
• **Assigned To**: {self.current_case.get('assigned_to', 'Legal Team')}

**Compliance Requirements:**
✅ Regulatory review completed
✅ Documentation gathered
⚠️ Risk assessment pending
⚠️ Final approval required

**Agent Notes:**
- Complex regulatory requirements
- Multiple stakeholders involved
- Timeline critical for compliance
- Consider external legal counsel"""

    def get_escalation_options(self) -> str:
        """Provide legal escalation information"""
        return """**🔺 Legal Escalation Options**

**Legal Team Escalation:**
- Senior Legal Counsel: ext. 5001
- Compliance Officer: ext. 5002
- Regulatory Affairs: ext. 5003

**Management Escalation:**
- Legal Director: Sarah Martinez (ext. 5004)
- Chief Compliance Officer: Robert Kim (ext. 5005)
- General Counsel: Lisa Thompson (ext. 5006)

**Specialized Legal Teams:**
- Data Privacy: ext. 5011
- Regulatory Compliance: ext. 5012
- Risk Management: ext. 5013
- External Counsel: ext. 5014

**Escalation Triggers:**
- Complex regulatory requirements
- High-risk compliance issues
- External legal counsel needed
- Regulatory enforcement actions

**Documentation Required:**
- Legal case summary and timeline
- Regulatory analysis and findings
- Risk assessment documentation
- Compliance impact assessment"""

    def get_general_agent_response(self) -> str:
        """General legal agent assistance"""
        return """**⚖️ Welcome to Legal Compliance Dashboard**

I'm here to help you with legal and compliance tasks. You can:

• Ask about specific cases (e.g., "CASE-0012345")
• Request case summaries
• Get legal escalation options
• Search compliance knowledge base

How can I assist you today?"""


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry agent."""
    global agent_executor_instance
    
    # Define agent skills
    skills = [
        AgentSkill(
            id='legal_compliance',
            name='Legal Compliance',
            description="Analyze compliance requirements for specific regulations (GDPR, SOX, CCPA, etc.) and provide regulatory guidance.",
            tags=['legal', 'compliance', 'gdpr', 'sox', 'ccpa', 'regulatory'],
            examples=[
                'Assess GDPR compliance for data processing',
                'Conduct SOX compliance audit',
                'Evaluate CCPA compliance requirements',
                'Analyze regulatory requirements for a business activity'
            ],
        ),
        AgentSkill(
            id='risk_assessment',
            name='Risk Assessment',
            description="Assess legal and compliance risks for business activities and provide mitigation strategies.",
            tags=['risk', 'assessment', 'legal', 'compliance', 'mitigation'],
            examples=[
                'Assess legal risks for a new business activity',
                'Evaluate compliance risks for data processing',
                'Provide risk mitigation strategies',
                'Conduct regulatory risk assessment'
            ],
        ),
        AgentSkill(
            id='regulatory_research',
            name='Regulatory Research',
            description="Research specific regulations and their requirements using legal databases and web search.",
            tags=['research', 'regulatory', 'legal', 'compliance', 'gdpr', 'sox'],
            examples=[
                'Research GDPR Article 6 requirements',
                'Find SOX Section 404 compliance requirements',
                'Look up CCPA data subject rights',
                'Research regulatory guidance for data transfers'
            ],
        ),
        AgentSkill(
            id='document_analysis',
            name='Document Analysis',
            description="Analyze legal documents, contracts, and compliance materials for regulatory requirements.",
            tags=['document', 'analysis', 'legal', 'contract', 'compliance'],
            examples=[
                'Analyze privacy policy for GDPR compliance',
                'Review data processing agreement',
                'Assess contract for regulatory requirements',
                'Analyze compliance documentation'
            ],
        ),
        AgentSkill(
            id='incident_response',
            name='Incident Response',
            description="Handle data breach and compliance incident reporting with proper procedures.",
            tags=['incident', 'response', 'breach', 'compliance', 'reporting'],
            examples=[
                'Create data breach incident report',
                'Generate compliance violation report',
                'Provide incident response procedures',
                'Assess incident severity and impact'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current legal and regulatory information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet', 'legal', 'regulatory'],
            examples=[
                'Find latest regulatory updates',
                'Search for legal precedents',
                'Get current compliance guidance',
                'Research regulatory enforcement actions'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded legal documents, compliance materials, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search', 'legal', 'compliance'],
            examples=[
                'Search legal documents for specific requirements',
                'Find compliance guidance in uploaded materials',
                'Extract regulatory information from documents',
                'Search through compliance policies'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    # Create agent card
    agent_card = AgentCard(
        name='Legal Compliance & Regulatory Agent',
        description="An intelligent legal and compliance agent specialized in regulatory analysis, risk assessment, document analysis, and incident response. Can analyze compliance requirements for GDPR, SOX, CCPA and other regulations, assess legal risks, research regulatory requirements, analyze legal documents, handle incident reporting, search the web for current legal information, and search through uploaded legal documents and compliance materials, all with professional legal guidance.",
       # url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent5/',
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )

    # Create agent executor
    agent_executor_instance = create_foundry_legal_agent_executor(agent_card)

    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor_instance, 
        task_store=InMemoryTaskStore()
    )

    # Create A2A application
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, 
        http_handler=request_handler
    )
    
    # Get routes
    routes = a2a_app.routes()
    
    # Add health check endpoint
    async def health_check(_request: Request) -> PlainTextResponse:
        return PlainTextResponse('AI Foundry Legal Agent is running!')
    
    routes.append(
        Route(
            path='/health',
            methods=['GET'],
            endpoint=health_check
        )
    )

    # Create Starlette app
    app = Starlette(routes=routes)
    
    return app


def run_a2a_server_in_thread(host: str, port: int):
    """Run A2A server in a separate thread."""
    print(f"Starting AI Foundry Expert Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
        # Wait a moment for server to fully start
        await asyncio.sleep(2)
        try:
            if not HOST_AGENT_URL:
                logger.info("ℹ️ Host agent URL not configured; skipping registration attempt.")
                return

            logger.info(f"🤝 Attempting to register '{agent_card.name}' with host agent at {HOST_AGENT_URL}...")
            registration_success = await register_with_host_agent(agent_card, host_url=HOST_AGENT_URL)
            if registration_success:
                logger.info(f"🎉 '{agent_card.name}' successfully registered with host agent!")
            else:
                logger.info(f"📡 '{agent_card.name}' registration failed - host agent may be unavailable")
        except Exception as e:
            logger.warning(f"⚠️ Registration attempt failed: {e}")


def start_background_registration(agent_card):
    """Start background registration task."""
    if SELF_REGISTRATION_AVAILABLE:
        def run_registration():
            asyncio.run(register_agent_with_host(agent_card))
        
        registration_thread = threading.Thread(target=run_registration, daemon=True)
        registration_thread.start()
        logger.info(f"🚀 '{agent_card.name}' starting with background registration enabled")
    else:
        logger.info(f"📡 '{agent_card.name}' starting without self-registration")


async def launch_ui(host: str = "0.0.0.0", ui_port: int = DEFAULT_UI_PORT, a2a_port: int = DEFAULT_PORT):
    """Launch Gradio UI and A2A server simultaneously."""
    print("Starting AI Foundry Expert Agent with both UI and A2A server...")
    
    # Verify required environment variables
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Initialize agents at startup BEFORE starting servers
    print("🚀 Initializing AI Foundry legal agents at startup...")
    try:
        await initialize_foundry_legal_agents_at_startup()
        print("✅ Legal agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize legal agents at startup: {e}")
        raise

    # Start A2A server in a separate thread
    a2a_thread = threading.Thread(
        target=run_a2a_server_in_thread,
        args=(host if host != "0.0.0.0" else DEFAULT_HOST, a2a_port),
        daemon=True
    )
    a2a_thread.start()
    
    # Give the A2A server a moment to start
    await asyncio.sleep(2)
    
    # Start background registration for UI mode
    skills = [
        AgentSkill(
            id='legal_compliance',
            name='Legal Compliance',
            description="Analyze compliance requirements for specific regulations (GDPR, SOX, CCPA, etc.) and provide regulatory guidance.",
            tags=['legal', 'compliance', 'gdpr', 'sox', 'ccpa', 'regulatory'],
            examples=[
                'Assess GDPR compliance for data processing',
                'Conduct SOX compliance audit',
                'Evaluate CCPA compliance requirements',
                'Analyze regulatory requirements for a business activity'
            ],
        ),
        AgentSkill(
            id='risk_assessment',
            name='Risk Assessment',
            description="Assess legal and compliance risks for business activities and provide mitigation strategies.",
            tags=['risk', 'assessment', 'legal', 'compliance', 'mitigation'],
            examples=[
                'Assess legal risks for a new business activity',
                'Evaluate compliance risks for data processing',
                'Provide risk mitigation strategies',
                'Conduct regulatory risk assessment'
            ],
        ),
        AgentSkill(
            id='regulatory_research',
            name='Regulatory Research',
            description="Research specific regulations and their requirements using legal databases and web search.",
            tags=['research', 'regulatory', 'legal', 'compliance', 'gdpr', 'sox'],
            examples=[
                'Research GDPR Article 6 requirements',
                'Find SOX Section 404 compliance requirements',
                'Look up CCPA data subject rights',
                'Research regulatory guidance for data transfers'
            ],
        ),
        AgentSkill(
            id='document_analysis',
            name='Document Analysis',
            description="Analyze legal documents, contracts, and compliance materials for regulatory requirements.",
            tags=['document', 'analysis', 'legal', 'contract', 'compliance'],
            examples=[
                'Analyze privacy policy for GDPR compliance',
                'Review data processing agreement',
                'Assess contract for regulatory requirements',
                'Analyze compliance documentation'
            ],
        ),
        AgentSkill(
            id='incident_response',
            name='Incident Response',
            description="Handle data breach and compliance incident reporting with proper procedures.",
            tags=['incident', 'response', 'breach', 'compliance', 'reporting'],
            examples=[
                'Create data breach incident report',
                'Generate compliance violation report',
                'Provide incident response procedures',
                'Assess incident severity and impact'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current legal and regulatory information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet', 'legal', 'regulatory'],
            examples=[
                'Find latest regulatory updates',
                'Search for legal precedents',
                'Get current compliance guidance',
                'Research regulatory enforcement actions'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded legal documents, compliance materials, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search', 'legal', 'compliance'],
            examples=[
                'Search legal documents for specific requirements',
                'Find compliance guidance in uploaded materials',
                'Extract regulatory information from documents',
                'Search through compliance policies'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='Legal Compliance & Regulatory Agent',
        description="An intelligent legal and compliance agent specialized in regulatory analysis, risk assessment, document analysis, and incident response. Can analyze compliance requirements for GDPR, SOX, CCPA and other regulations, assess legal risks, research regulatory requirements, analyze legal documents, handle incident reporting, search the web for current legal information, and search through uploaded legal documents and compliance materials, all with professional legal guidance.",
        #url=f'http://{host if host != "0.0.0.0" else DEFAULT_HOST}:{a2a_port}/',
        #url=f'https://agent1.ngrok.app/agent5/',
        url=resolve_agent_url(resolved_host_for_url, a2a_port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)

    def check_pending_requests():
        """Check for pending expert requests."""
        global agent_executor_instance
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            context_id = next(iter(agent_executor_instance._waiting_for_input.keys()))
            request_text = agent_executor_instance._waiting_for_input[context_id]
            
            # DEBUG: Log the full request text to see what we're getting
            logger.debug(f"Full request text length: {len(request_text)}")
            logger.debug(f"Request text preview: {request_text[:500]}...")
            
            # Extract conversation history from the memory results
            conversation_text = ""
            if "Relevant context from previous interactions:" in request_text:
                import json
                import re
                
                # Find all the memory result entries
                # Pattern: "  {number}. From {agent_name}: {content}"
                memory_pattern = r'\s+(\d+)\.\s+From\s+([^:]+):\s+(.+)'
                matches = re.findall(memory_pattern, request_text)
                
                logger.debug(f"Found {len(matches)} memory matches")
                
                for i, match in enumerate(matches):
                    try:
                        _, agent_name, content = match
                        logger.debug(f"Processing memory match {i+1}: agent={agent_name}, content_length={len(content)}")
                        logger.debug(f"Content preview: {content[:200]}...")
                        
                        # The content might be a JSON string or just text
                        if content.startswith('{'):
                            # Try to parse as Python dict (since it uses single quotes)
                            try:
                                import ast
                                # Find the end of the dict object (before the ...)
                                if '...' in content:
                                    content = content.split('...')[0]
                                    # Try to find the closing brace
                                    brace_count = 0
                                    end_pos = 0
                                    for i, char in enumerate(content):
                                        if char == '{':
                                            brace_count += 1
                                        elif char == '}':
                                            brace_count -= 1
                                            if brace_count == 0:
                                                end_pos = i + 1
                                                break
                                    if end_pos > 0:
                                        content = content[:end_pos]
                                
                                data = ast.literal_eval(content)
                                logger.debug(f"Parsed JSON keys: {list(data.keys())}")
                                
                                # Look for conversation history in the JSON
                                if 'inbound_payload' in data:
                                    inbound = data['inbound_payload']
                                    logger.debug(f"Found inbound_payload, type: {type(inbound)}, length: {len(str(inbound))}")
                                    
                                    if isinstance(inbound, str):
                                        try:
                                            # Handle truncated JSON in inbound_payload
                                            if '...' in inbound:
                                                inbound = inbound.split('...')[0]
                                                # Try to find the closing brace
                                                brace_count = 0
                                                end_pos = 0
                                                for i, char in enumerate(inbound):
                                                    if char == '{':
                                                        brace_count += 1
                                                    elif char == '}':
                                                        brace_count -= 1
                                                        if brace_count == 0:
                                                            end_pos = i + 1
                                                            break
                                                if end_pos > 0:
                                                    inbound = inbound[:end_pos]
                                            
                                            inbound_data = json.loads(inbound)
                                            logger.debug(f"Parsed inbound_data keys: {list(inbound_data.keys())}")
                                            
                                            if 'history' in inbound_data and inbound_data['history']:
                                                logger.debug(f"Found history with {len(inbound_data['history'])} messages")
                                                for j, msg in enumerate(inbound_data['history']):
                                                    logger.debug(f"History message {j}: {msg}")
                                                    if 'parts' in msg and msg['parts']:
                                                        for part in msg['parts']:
                                                            if 'root' in part and 'text' in part['root']:
                                                                text = part['root']['text']
                                                                if text.strip():
                                                                    conversation_text += f"{text}\n"
                                                                    logger.debug(f"Added conversation text: {text[:100]}...")
                                            else:
                                                logger.debug(f"No history found in inbound_data")
                                                
                                            # Also try to extract from the raw inbound_payload string if history is empty
                                            if not conversation_text and isinstance(inbound, str):
                                                # Look for conversation patterns in the raw string
                                                # Common patterns: "text": "actual message content"
                                                text_pattern = r'"text":\s*"([^"]*)"'
                                                text_matches = re.findall(text_pattern, inbound)
                                                if text_matches:
                                                    logger.debug(f"Found {len(text_matches)} text matches in raw payload")
                                                    for text_match in text_matches:
                                                        if text_match.strip() and len(text_match.strip()) > 10:  # Only meaningful content
                                                            conversation_text += f"{text_match.strip()}\n"
                                                            logger.debug(f"Added raw text: {text_match.strip()[:100]}...")
                                        except Exception as e:
                                            logger.debug(f"Error parsing inbound_payload: {e}")
                                            # If parsing fails, just show the raw inbound_payload
                                            conversation_text += f"Raw payload: {inbound[:200]}...\n"
                            except Exception as e:
                                logger.debug(f"Error parsing JSON: {e}")
                                # If not valid JSON, just use the content as text
                                conversation_text += f"Raw content: {content[:200]}...\n"
                        else:
                            # Just use the content as text
                            conversation_text += f"{content}\n"
                            
                        # Additional fallback: try to extract conversation from the raw content
                        if not conversation_text.strip():
                            # Look for any text patterns in the raw content
                            text_pattern = r'"text":\s*"([^"]*)"'
                            text_matches = re.findall(text_pattern, content)
                            if text_matches:
                                logger.debug(f"Found {len(text_matches)} text matches in raw content")
                                for text_match in text_matches:
                                    if text_match.strip() and len(text_match.strip()) > 10:  # Only meaningful content
                                        conversation_text += f"{text_match.strip()}\n"
                                        logger.debug(f"Added raw content text: {text_match.strip()[:100]}...")
                    except Exception as e:
                        logger.debug(f"Error processing memory match: {e}")
                        continue
            
            logger.debug(f"Final conversation text length: {len(conversation_text)}")
            logger.debug(f"Conversation text: {conversation_text}")
            
            # Add static conversation data for human intervention scenarios
            static_conversation = """Assistant: Hello! How can I help you today?

User: Hello my name is David Miller, I noticed a large transcation on my credit card tha tI did not do. I'm not happy

Thank you for reaching out, David Miller. I understand how concerning it can be to discover a large unauthorized transaction on your credit card. I'm here to assist you in resolving this issue as quickly as possible.

Could you provide the following details to proceed?

Assistant: Transaction Amount
Date of Transaction
Any Merchant or Transaction Details (if available)
I'll ensure your concern is escalated to the appropriate team and actions like blocking the card and initiating an investigation are taken promptly. Let me know if there's anything else you'd like me to prioritize.

User: 1500$, yesterday"""
            
            # Combine extracted conversation with static data
            full_conversation = static_conversation
            if conversation_text.strip():
                full_conversation += f"\n\n--- Additional Context from Memory ---\n{conversation_text}"
            
            # Display the conversation history
            return f"""
<div style="background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%); color: white; padding: 20px; border-radius: 10px; margin: 10px 0; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
<h2 style="margin: 0 0 15px 0; color: white;">🚨 URGENT: PENDING REQUEST FROM HOST AGENT</h2>
<div style="background: rgba(255, 255, 255, 0.1); padding: 15px; border-radius: 8px; margin: 10px 0; white-space: pre-wrap; font-family: monospace; font-size: 12px; color: white;">
{full_conversation}
</div>
<div style="margin-top: 15px; padding: 10px; background: rgba(255, 255, 255, 0.2); border-radius: 5px; text-align: center;">
<strong>⏰ ACTION REQUIRED: Please respond in the chat below to provide your expert input.</strong>
</div>
</div>
"""
        return """
<div style="background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: white; padding: 15px; border-radius: 8px; margin: 10px 0; text-align: center;">
<h3 style="margin: 0; color: white;">✅ Status: No pending requests - Ready for new expert consultations</h3>
</div>
"""

    # Create dashboard instance
    dashboard = LegalComplianceDashboard()
    
    def format_case_info(case):
        """Format legal case information for display"""
        # Set priority icon based on value
        if case.get('priority') == 'Low':
            priority_icon = '🟢'
        elif case.get('priority') == 'Medium':
            priority_icon = '🟡'
        elif case.get('priority') == 'High':
            priority_icon = '🔴'
        elif case.get('priority') == 'Critical':
            priority_icon = '🚨'
        else:
            priority_icon = '⚪'
            
        return f"""
**Case ID:** {case.get('case_id', 'N/A')}  
**Client:** {case.get('client_name', 'N/A')}  
**Contact:** {case.get('contact', 'N/A')}  
**Email:** [{case.get('email', 'N/A')}](mailto:{case.get('email', 'N/A')})  
**Phone:** {case.get('phone', 'N/A')}  
**Case Type:** {case.get('case_type', 'N/A')}  
**Priority:** {priority_icon} {case.get('priority', 'N/A')}  
**Status:** {case.get('status', 'N/A')}  
**Assigned Attorney:** {case.get('assigned_attorney', 'N/A')}  
**Last Updated:** {case.get('last_updated', 'N/A')}  
**Compliance Deadline:** {case.get('compliance_deadline', 'N/A')}
"""
    
    def format_accounts_table(accounts):
        """Format accounts as a table"""
        df = pd.DataFrame(accounts)
        return df
    
    def format_tickets_table(tickets):
        """Format tickets as a table"""
        df = pd.DataFrame(tickets)
        return df
    
    def format_transactions_table(transactions):
        """Format transactions as a table"""
        df = pd.DataFrame(transactions)
        return df
    
    def refresh_case_data():
        """Refresh case information display"""
        global agent_executor_instance
        
        # Check if there are pending requests and switch cases accordingly
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            dashboard.switch_to_sox_audit()
        else:
            dashboard.switch_to_gdpr_compliance()
        
        data = dashboard.get_dashboard_data()
        return (
            format_case_info(data["case"]),
            format_accounts_table(data["accounts"]),
            format_tickets_table(data["tickets"]),
            format_transactions_table(data["transactions"]),
            data["analytics"]
        )

    # Custom CSS for dashboard styling
    dashboard_css = """
    .gradio-container {
        max-width: 1400px !important;
        margin: auto !important;
    }
    .dashboard-header {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
        color: white !important;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 20px;
        text-align: center;
    }
    .dashboard-header h1,
    .dashboard-header h3,
    .dashboard-header p {
        color: white !important;
    }
    .case-info {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        color: #1f2937 !important;
        font-weight: 500;
    }
    .case-info p {
        color: #1f2937 !important;
        margin: 8px 0;
        line-height: 1.5;
    }
    .case-info strong {
        color: #1e3a8a !important;
        font-weight: 600;
    }
    .priority-high {
        color: #dc2626;
        font-weight: bold;
    }
    .priority-medium {
        color: #d97706;
        font-weight: bold;
    }
    .status-active {
        color: #059669;
        font-weight: bold;
    }
    .chat-container {
        border: 2px solid #1e3a8a;
        border-radius: 8px;
    }
    /* Fix Gradio footer text contrast */
    footer {
        color: #374151 !important;
    }
    footer a {
        color: #1e3a8a !important;
        text-decoration: none;
    }
    footer a:hover {
        color: #3b82f6 !important;
        text-decoration: underline;
    }
    /* Target the specific footer elements */
    .footer {
        color: #374151 !important;
    }
    .footer span, .footer div {
        color: #374151 !important;
    }
    """

    display_host = resolved_host_for_url
    ui_display_url = f"http://{display_host}:{ui_port}"
    a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')

    with gr.Blocks(css=dashboard_css, theme=gr.themes.Ocean(), title="Legal Compliance Dashboard - AI Foundry Legal Agent") as demo:
        
        # Dashboard Header
        gr.HTML(f"""
        <div class="dashboard-header">
            <div style="display: flex; align-items: center; justify-content: center; gap: 15px;">
                <div>
                    <h1 style="margin: 0;">Legal Compliance Agent (A2A)</h1>
                    <h3 style="margin: 5px 0;">An intelligent Azure Foundry agent specialized in legal compliance, regulatory research, risk assessment, and document analysis.</h3>
                    <p style="margin: 5px 0;">Legal Workstation | Session: Active | Time: <span id="current-time"></span></p>
                    <p style="margin: 5px 0;"><strong>Direct UI Access:</strong> {ui_display_url} | <strong>A2A API Access:</strong> {a2a_display_url}</p>
                </div>
            </div>
        </div>
        """)
        
        # Status display for pending requests (preserved from original) - full width
        status_display = gr.HTML(value=check_pending_requests())
        
        with gr.Row():
            gr.Column(scale=4)  # Empty space
            refresh_btn = gr.Button("🔄 Refresh Status", size="sm", scale=1)
            refresh_btn.click(fn=check_pending_requests, outputs=status_display)
        
        # Set up automatic refresh using timer (every 2 seconds) - will be configured later
        timer = gr.Timer(2)
        
        # Add a hidden component that triggers refresh via JavaScript
        gr.HTML("""
        <script>
        setInterval(function() {
            // Find the refresh button by its text content
            const buttons = document.querySelectorAll('button');
            for (let btn of buttons) {
                if (btn.textContent.includes('🔄 Refresh Status')) {
                    btn.click();
                    break;
                }
            }
        }, 3000);
        </script>
        """, visible=False)
        
        # Agent Support Chat - Full Width
        gr.Markdown("### 💬 Agent Support Chat")
        
        chatbot_interface = gr.Chatbot(
            value=[{"role": "assistant", "content": dashboard.get_general_agent_response()}],
            height=400,
            show_label=False,
            container=True,
            elem_classes=["chat-container"],
            type="messages"
        )
        
        with gr.Row():
            agent_input = gr.Textbox(
                placeholder="Ask about tickets, accounts, or type ticket number (e.g., INC0012345)...",
                show_label=False,
                scale=4
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)
        
        # Agent Quick Commands
        with gr.Row():
            def set_tickets_query():
                return "show all open tickets"
            
            def set_account_summary():
                return "account summary"
            
            def set_escalation():
                return "escalation options"
            
            def set_knowledge_base():
                return "search knowledge base"
            
            gr.Button("🎫 View Tickets", size="sm").click(
                set_tickets_query,
                outputs=agent_input
            )
            gr.Button("💰 Account Summary", size="sm").click(
                set_account_summary,
                outputs=agent_input
            )
            gr.Button("🔺 Escalate", size="sm").click(
                set_escalation,
                outputs=agent_input
            )
            gr.Button("📋 Knowledge Base", size="sm").click(
                set_knowledge_base,
                outputs=agent_input
            )
        
        # Quick Actions - Full Width
        gr.Markdown("### ⚡ Quick Actions")
        with gr.Row():
            gr.Button("🔒 Reset Password", size="sm")
            gr.Button("❄️ Freeze Account", size="sm")
            gr.Button("💳 Order Card", size="sm")
            gr.Button("📧 Send Email", size="sm")
        
        # Customer Information and Account Details Section
        with gr.Row():
            # Left Panel - Customer Information, Accounts, Tickets, Transactions
            with gr.Column(scale=1):
                gr.Markdown("### ⚖️ Case Information")
                case_info = gr.Markdown(
                    format_case_info(dashboard.current_case),
                    elem_classes=["case-info"]
                )
                
                gr.Markdown("### 💳 Account Overview")
                accounts_table = gr.Dataframe(
                    value=format_accounts_table(dashboard.accounts),
                    headers=["Account Type", "Number", "Balance", "Status", "Last Transaction"],
                    interactive=False
                )
                
                gr.Markdown("### 🎫 Open Salesforce Cases")
                tickets_table = gr.Dataframe(
                    value=format_tickets_table(dashboard.open_tickets),
                    headers=["Ticket ID", "Priority", "Status", "Subject", "Created", "Assigned To", "Last Update", "Description", "Resolution Time"],
                    interactive=False
                )
                
                gr.Markdown("### 💸 Recent Transactions")
                transactions_table = gr.Dataframe(
                    value=format_transactions_table(dashboard.recent_transactions),
                    headers=["Date", "Description", "Amount", "Account"],
                    interactive=False
                )
            
            # Right Panel - Customer Analytics
            with gr.Column(scale=1):
                gr.Markdown("### 📊 Case Analytics & Services")
                customer_analytics = gr.HTML(value=dashboard.get_case_analytics())

        
        # Agent Tools Panel
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🛠️ Agent Tools")
                with gr.Row():
                    gr.Button("📊 Generate Report", variant="secondary")
                    gr.Button("📞 Schedule Callback", variant="secondary")
                    gr.Button("✉️ Send Secure Message", variant="secondary")
                    gr.Button("🔄 Refresh Data", variant="secondary").click(
                        refresh_case_data,
                        outputs=[case_info, accounts_table, tickets_table, transactions_table, customer_analytics]
                    )
        
        # Status Bar
        gr.HTML("""
        <div style="background: #f1f5f9; padding: 10px; border-radius: 5px; margin-top: 20px; text-align: center; font-size: 12px; color: #1f2937; font-weight: 500;">
            <strong style="color: #1e3a8a;">Agent Status:</strong> Available | 
            <strong style="color: #1e3a8a;">Queue:</strong> 3 customers waiting | 
            <strong style="color: #1e3a8a;">Avg Handle Time:</strong> 4:32 | 
            <strong style="color: #1e3a8a;">Cases Today:</strong> 12 resolved | 
            <strong style="color: #1e3a8a;">System Status:</strong> 🟢 All systems operational
        </div>
        """)
        
        # Event handlers for dashboard chat
        async def chat_response(message: str, history: List[dict]) -> Tuple[str, List[dict]]:
            """Process agent chat messages - handles both dashboard and AI Foundry queries"""
            global agent_executor_instance
            
            if not message.strip():
                return "", history
            
            # Check if this is a dashboard-specific query first (using precise word matching)
            query_lower = message.lower()
            # Use word boundaries to avoid false matches like "incident" matching "inc"
            import re
            dashboard_patterns = [
                r'\binc\d+',  # Match INC followed by numbers (e.g., INC0012345)
                r'\breq\d+',  # Match REQ followed by numbers  
                r'\bticket\s+\d+',  # Match "ticket" followed by numbers
                r'\baccount\s+balance\b',  # Match specific phrase
                r'\bescalate\b',  # Match whole word only
                r'\blogin\s+issue\b',  # Match specific phrase
                r'\bpassword\s+reset\b',  # Match specific phrase
                r'\bcredit\s+limit\b'  # Match specific phrase
            ]
            
            is_dashboard_query = any(re.search(pattern, query_lower) for pattern in dashboard_patterns)
            
            if is_dashboard_query:
                # Handle as dashboard query
                response = dashboard.process_agent_query(message)
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": response})
                return "", history
            else:
                # Handle as AI Foundry query - check for pending requests first
                if agent_executor_instance and agent_executor_instance._waiting_for_input:
                    context_id = next(iter(agent_executor_instance._waiting_for_input.keys()))
                    request_text = agent_executor_instance._waiting_for_input[context_id]
                    
                    # This is the human expert's response to a pending request
                    history.append({"role": "user", "content": message})
                    history.append({"role": "assistant", "content": f"✅ **Sending your response to Host Agent...**\n\nExpert Response: \"{message}\""})
                    
                    # Send the human response to complete the waiting task
                    success = await agent_executor_instance.send_human_response(context_id, message)
                    
                    if success:
                        history.append({"role": "assistant", "content": "✅ **Response sent successfully!** The Host Agent has received your expert input and will continue processing."})
                    else:
                        history.append({"role": "assistant", "content": "❌ **Error:** Could not send response to Host Agent. The task may have expired."})
                    
                    return "", history
                
                # Regular AI Foundry interaction
                try:
                    # Get the shared agent that was initialized at startup
                    foundry_agent = await FoundryLegalAgentExecutor.get_shared_agent()
                    
                    if not foundry_agent:
                        history.append({"role": "assistant", "content": "❌ Agent not initialized. Please restart the application."})
                        return "", history
                    
                    # Create a thread for this conversation
                    thread = await foundry_agent.create_thread()
                    thread_id = thread.id
                    
                    # Add processing message
                    history.append({"role": "user", "content": message})
                    history.append({"role": "assistant", "content": "🤖 **Processing your request...**"})
                    
                    # Run the conversation using the streaming method
                    response_count = 0
                    async for response in foundry_agent.run_conversation_stream(thread_id, message):
                        if isinstance(response, str):
                            if response.strip():
                                # Filter out processing messages
                                if not any(phrase in response.lower() for phrase in [
                                    "processing your request", "🤖 processing", "processing..."
                                ]):
                                    history.append({"role": "assistant", "content": response})
                                    response_count += 1
                        else:
                            # handle other types if needed
                            history.append({"role": "assistant", "content": f"An error occurred while processing your request: {str(response)}. Please check the server logs for details."})
                            response_count += 1
                    
                    # If no responses were yielded, show a default message
                    if response_count == 0:
                        history.append({"role": "assistant", "content": "I processed your request but didn't receive a response. Please try again."})
                    
                except Exception as e:
                    logger.error(f"Error in chat_response (Type: {type(e)}): {e}")
                    traceback.print_exc()
                    history.append({"role": "assistant", "content": f"An error occurred while processing your request: {str(e)}. Please check the server logs for details."})
                
                return "", history
        
        # Create a synchronous wrapper for the async function
        def sync_chat_response(message: str, history: List[dict]) -> Tuple[str, List[dict]]:
            """Synchronous wrapper for async chat_response"""
            return asyncio.run(chat_response(message, history))
        
        send_btn.click(
            sync_chat_response,
            inputs=[agent_input, chatbot_interface],
            outputs=[agent_input, chatbot_interface]
        )
        
        agent_input.submit(
            sync_chat_response,
            inputs=[agent_input, chatbot_interface],
            outputs=[agent_input, chatbot_interface]
        )
        
        # Configure the timer now that all components are defined
        def combined_refresh():
            """Combined refresh for both status and case data"""
            global agent_executor_instance
            
            # Check if there are pending requests and switch cases accordingly
            if agent_executor_instance and agent_executor_instance._waiting_for_input:
                dashboard.switch_to_sox_audit()
            else:
                dashboard.switch_to_gdpr_compliance()
            
            data = dashboard.get_dashboard_data()
            return (
                check_pending_requests(),
                format_case_info(data["case"]),
                format_accounts_table(data["accounts"]),
                format_tickets_table(data["tickets"]),
                format_transactions_table(data["transactions"]),
                data["analytics"]
            )
        
        timer.tick(fn=combined_refresh, outputs=[status_display, case_info, accounts_table, tickets_table, transactions_table, customer_analytics])

    print(f"Launching AI Foundry Legal Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Foundry Legal Agent Gradio application has been shut down.")


async def main_async(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for Azure Foundry agent with startup initialization."""
    # Verify required environment variables
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Initialize agents at startup BEFORE starting server
    print("🚀 Initializing AI Foundry legal agents at startup...")
    try:
        await initialize_foundry_legal_agents_at_startup()
        print("✅ Legal agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize legal agents at startup: {e}")
        raise

    print(f"Starting AI Foundry Legal Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = [
        AgentSkill(
            id='legal_compliance',
            name='Legal Compliance',
            description="Analyze compliance requirements for specific regulations (GDPR, SOX, CCPA, etc.) and provide regulatory guidance.",
            tags=['legal', 'compliance', 'gdpr', 'sox', 'ccpa', 'regulatory'],
            examples=[
                'Assess GDPR compliance for data processing',
                'Conduct SOX compliance audit',
                'Evaluate CCPA compliance requirements',
                'Analyze regulatory requirements for a business activity'
            ],
        ),
        AgentSkill(
            id='risk_assessment',
            name='Risk Assessment',
            description="Assess legal and compliance risks for business activities and provide mitigation strategies.",
            tags=['risk', 'assessment', 'legal', 'compliance', 'mitigation'],
            examples=[
                'Assess legal risks for a new business activity',
                'Evaluate compliance risks for data processing',
                'Provide risk mitigation strategies',
                'Conduct regulatory risk assessment'
            ],
        ),
        AgentSkill(
            id='regulatory_research',
            name='Regulatory Research',
            description="Research specific regulations and their requirements using legal databases and web search.",
            tags=['research', 'regulatory', 'legal', 'compliance', 'gdpr', 'sox'],
            examples=[
                'Research GDPR Article 6 requirements',
                'Find SOX Section 404 compliance requirements',
                'Look up CCPA data subject rights',
                'Research regulatory guidance for data transfers'
            ],
        ),
        AgentSkill(
            id='document_analysis',
            name='Document Analysis',
            description="Analyze legal documents, contracts, and compliance materials for regulatory requirements.",
            tags=['document', 'analysis', 'legal', 'contract', 'compliance'],
            examples=[
                'Analyze privacy policy for GDPR compliance',
                'Review data processing agreement',
                'Assess contract for regulatory requirements',
                'Analyze compliance documentation'
            ],
        ),
        AgentSkill(
            id='incident_response',
            name='Incident Response',
            description="Handle data breach and compliance incident reporting with proper procedures.",
            tags=['incident', 'response', 'breach', 'compliance', 'reporting'],
            examples=[
                'Create data breach incident report',
                'Generate compliance violation report',
                'Provide incident response procedures',
                'Assess incident severity and impact'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current legal and regulatory information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet', 'legal', 'regulatory'],
            examples=[
                'Find latest regulatory updates',
                'Search for legal precedents',
                'Get current compliance guidance',
                'Research regulatory enforcement actions'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded legal documents, compliance materials, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search', 'legal', 'compliance'],
            examples=[
                'Search legal documents for specific requirements',
                'Find compliance guidance in uploaded materials',
                'Extract regulatory information from documents',
                'Search through compliance policies'
            ],
        )
    ]

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST

    agent_card = AgentCard(
        name='Legal Compliance & Regulatory Agent',
        description="An intelligent legal and compliance agent specialized in regulatory analysis, risk assessment, document analysis, and incident response. Can analyze compliance requirements for GDPR, SOX, CCPA and other regulations, assess legal risks, research regulatory requirements, analyze legal documents, handle incident reporting, search the web for current legal information, and search through uploaded legal documents and compliance materials, all with professional legal guidance.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent5/',
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)
    
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Synchronous wrapper for main_async."""
    asyncio.run(main_async(host, port))


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A server')
@click.option('--ui', is_flag=True, help='Launch Gradio UI (also runs A2A server)')
@click.option('--ui-port', 'ui_port', default=DEFAULT_UI_PORT, help='Port for Gradio UI (only used with --ui flag)')
def cli(host: str, port: int, ui: bool, ui_port: int):
    """AI Foundry Legal Agent - can run as A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
