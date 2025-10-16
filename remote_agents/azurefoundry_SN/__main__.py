import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
from pprint import pformat
import threading
import json
import datetime
import random
import re
import html
from typing import Dict, List, Tuple, Optional
import pandas as pd
import base64

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_agents_at_startup, FoundryAgentExecutor
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import self-registration utility
try:
    from utils.self_registration import register_with_host_agent
    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError:
    # Fallback if utils not available
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    SELF_REGISTRATION_AVAILABLE = False

DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 8000
DEFAULT_UI_PORT = 8085

# UI Configuration
APP_NAME = "foundry_expert_app"
USER_ID = "default_user"
SESSION_ID = "default_session"

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None

# Persist a single Azure Foundry thread per UI session
ui_thread_id: Optional[str] = None

# Global state for UI notifications
pending_request_notification = {"has_pending": False, "request_text": "", "context_id": ""}

CITIBANK_HOST_AGENT_URL = "http://localhost:12000"
#CITIBANK_HOST_AGENT_URL = "https://citibank-host-agent.whiteplant-4c581c75.canadaeast.azurecontainerapps.io"
#CITIBANK_HOST_AGENT_URL = "https://contoso-a2a.whiteplant-4c581c75.canadaeast.azurecontainerapps.io"


class SupportDashboard:
    def __init__(self):
        # Ana Lucia customer data (default)
        self.ana_lucia_customer = {
            "customer_id": "1348784",
            "name": "Ana Lucia Ribeiro",
            "phone": "+55-21-99123-8822",
            "email": "analucia.ribeiro@email.com",
            "join_date": "May 5, 2010",
            "customer_tier": "gold",
            "relationship_manager": "Rafael Santos",
            "last_login": "July 3, 2025 - 10:44 PM UTC",
            "authentication_status": "Verified",
            "risk_level": "Low"
        }
        
        # David Miller customer data (for human requests)
        self.david_miller_customer = {
            "customer_id": "789456123",
            "name": "David Miller",
            "phone": "+1 (555) 123-4567",
            "email": "david.miller@email.com",
            "join_date": "March 15, 2019",
            "customer_tier": "Priority",
            "relationship_manager": "Michael Chen",
            "last_login": "January 15, 2024 - 2:30 PM EST",
            "authentication_status": "Verified",
            "risk_level": "High"
        }
        
        # Set default customer to Ana Lucia
        self.current_customer = self.ana_lucia_customer
        
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
        
        # David Miller account information (for human requests)
        self.david_miller_accounts = [
            {
                "account_type": "Checking",
                "account_number": "****1234",
                "balance": "$12,450.67",
                "status": "Active",
                "last_transaction": "Jan 15, 2024"
            },
            {
                "account_type": "Savings",
                "account_number": "****5678",
                "balance": "$45,230.12",
                "status": "Active", 
                "last_transaction": "Jan 12, 2024"
            },
            {
                "account_type": "Credit Card",
                "account_number": "****9012",
                "balance": "$2,340.50",
                "status": "Active",
                "last_transaction": "Jan 15, 2024"
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
- Document resolution in ServiceNow""",
                
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

    def switch_to_david_miller(self):
        """Switch to David Miller's profile for human requests"""
        self.current_customer = self.david_miller_customer
        self.accounts = self.david_miller_accounts
    
    def switch_to_ana_lucia(self):
        """Switch back to Ana Lucia's profile (default)"""
        self.current_customer = self.ana_lucia_customer
        self.accounts = self.ana_lucia_accounts
    
    def get_customer_analytics(self):
        """Get customer analytics based on current customer"""
        if self.current_customer == self.ana_lucia_customer:
            return """
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #1e3a8a; margin: 0 0 10px 0;">🏦 Account Health & Metrics</h4>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Account Health:</strong> ✅ Excellent</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Customer Since:</strong> 15+ years</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Satisfaction Score:</strong> 4.9/5.0</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Digital Engagement:</strong> Very Active</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Risk Profile:</strong> 🟢 Low Risk</p>
            </div>
            
            <div style="background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #0369a1; margin: 0 0 10px 0;">💳 Active Products</h4>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Prestige Card</strong> - R$70,000 limit</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Gold Banking</strong> - Private Client</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Conta Corrente</strong> - BRL/USD</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Poupança Premium</strong> - High Yield</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">PIX & Mobile Banking</strong></p>
            </div>
            
            <div style="background: #f0fdf4; border: 1px solid #22c55e; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #15803d; margin: 0 0 10px 0;">🎯 Recommended Services</h4>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Travel Insurance</strong> - Portugal Trip</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Currency Exchange</strong> - EUR preferred rates</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Investment Advisory</strong> - Portfolio Growth</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Private Pass</strong> - Cultural Events</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">International ATM</strong> - Fee Rebates</p>
            </div>
            
            <div style="background: #fefce8; border: 1px solid #eab308; border-radius: 8px; padding: 15px;">
                <h4 style="color: #a16207; margin: 0 0 10px 0;">📈 Usage Insights</h4>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Monthly Spending:</strong> R$6,800 avg</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Top Categories:</strong> Travel, Groceries, Online</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">International Usage:</strong> 20% of transactions</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Digital Payments:</strong> 90% mobile/PIX</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Branch Visits:</strong> Ipanema VIP (Monthly)</p>
            </div>
            """
        else:  # David Miller
            return """
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #1e3a8a; margin: 0 0 10px 0;">🏦 Account Health & Metrics</h4>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Account Health:</strong> ⚠️ Satisfactory</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Customer Since:</strong> 5+ years</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Satisfaction Score:</strong> 4.8/5.0</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Digital Engagement:</strong> Very Active</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Risk Profile:</strong> 🟡 Medium Risk</p>
            </div>  
            
            <div style="background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #0369a1; margin: 0 0 10px 0;">💳 Active Products</h4>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Double Cash Card</strong> - Premium Rewards</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Priority</strong> - Relationship Banking</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Checking Account</strong> - No minimum</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Savings Plus</strong> - High Yield</p>
                <p style="color: #1f2937;">✅ <strong style="color: #1f2937;">Online & Mobile Banking</strong></p>
            </div>
            
            <div style="background: #f0fdf4; border: 1px solid #22c55e; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h4 style="color: #15803d; margin: 0 0 10px 0;">🎯 Recommended Services</h4>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Private Pass</strong> - Exclusive Events</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Investment Advisory</strong> - Wealth Management</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Credit Limit Increase</strong> - Pre-approved</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Auto Loan</strong> - Preferred Rates</p>
                <p style="color: #1f2937;">🔹 <strong style="color: #1f2937;">Home Equity Line</strong> - Low APR</p>
            </div>
            
            <div style="background: #fefce8; border: 1px solid #eab308; border-radius: 8px; padding: 15px;">
                <h4 style="color: #a16207; margin: 0 0 10px 0;">📈 Usage Insights</h4>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Monthly Spending:</strong> $4,200 avg</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Top Categories:</strong> Dining, Shopping, Gas</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">International Usage:</strong> 8% of transactions</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Digital Payments:</strong> 85% mobile/online</p>
                <p style="color: #1f2937;"><strong style="color: #1f2937;">Branch Visits:</strong> Quarterly (Priority Service)</p>
            </div>
            """
    
    def get_dashboard_data(self):
        """Return all dashboard data for display"""
        return {
            "customer": self.current_customer,
            "accounts": self.accounts,
            "tickets": self.open_tickets,
            "transactions": self.recent_transactions,
            "analytics": self.get_customer_analytics()
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
        """Provide account summary for agent"""
        total_deposits = sum(float(acc["balance"].replace("$", "").replace(",", "")) 
                           for acc in self.accounts if acc["account_type"] in ["Checking", "Savings"])
        
        return f"""**💰 Account Summary for {self.current_customer['name']}**

**Total Relationship Value**: ${total_deposits:,.2f}
**Customer Tier**: {self.current_customer['customer_tier']}
**Risk Level**: {self.current_customer['risk_level']}

**Account Details:**
• **Checking (****1234)**: $12,450.67 - Active
• **Savings (****5678)**: $45,230.12 - Active  
• **Credit Card (****9012)**: $2,340.50 balance - Active

**Recent Activity Flags:**
✅ Regular salary deposits
✅ Normal spending patterns
⚠️ Credit utilization at 46.8%

**Agent Notes:**
- Long-term customer (5+ years)
- Excellent payment history
- Eligible for premium services
- Consider credit limit increase approval"""

    def get_escalation_options(self) -> str:
        """Provide escalation information"""
        return """**🔺 Escalation Options**

**Level 2 Support:**
- Digital Banking Team: ext. 2847
- Credit Operations: ext. 2156
- Technical Support: ext. 2934

**Management Escalation:**
- Team Lead: Sarah Martinez (ext. 2001)
- Department Manager: Robert Kim (ext. 2002)
- Regional Director: Lisa Thompson (ext. 2003)

**Specialized Teams:**
- Fraud Prevention: ext. 2911 (24/7)
- VIP Customer Service: ext. 2500
- Compliance Team: ext. 2777

**Escalation Triggers:**
- Customer dissatisfaction
- Technical complexity beyond L1
- Policy exceptions required
- Regulatory compliance issues

**Documentation Required:**
- Case summary and timeline
- Customer interaction history
- Resolution attempts made
- Business impact assessment"""

    def get_general_agent_response(self) -> str:
        """General agent assistance"""
        return """**🏦 Welcome to Customer Support Dashboard**

I'm here to help you with customer support tasks. You can:

• Ask about specific tickets (e.g., "INC0012345")
• Request account summaries
• Get escalation options
• Search the knowledge base

How can I assist you today?"""


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for Azure Foundry agent."""
    global agent_executor_instance
    
    # Define agent skills
    skills = [
        AgentSkill(
                id='salesforce_management',
                name='ServiceNow Management',
                description="Create, search, and manage ServiceNow incidents, users, and knowledge base articles. Simulates ServiceNow actions with realistic synthetic data.",
                tags=['servicenow', 'incident', 'it', 'support'],
                examples=[
                    'Create a new ServiceNow incident',
                    'Search for incidents assigned to a user',
                    'Update incident status',
                    'List ServiceNow users',
                    'Search ServiceNow knowledge base'
                ],
            ),
        AgentSkill(
            id='Bank_actions',
            name='Bank Actions',
            description="Simulate any action on the Bank system (block/unblock card, check balance, report fraud, create disputes, issue refunds, etc.) and return synthetic responses.",
            tags=['banking', 'finance', 'card', 'dispute', 'refund'],
            examples=[
                'Block a credit card',
                'Unblock a credit card',
                'Check account balance',
                'Report a fraudulent transaction',
                'Create a dispute for a transaction',
                'Issue a refund for a transaction',
                'Check transaction details'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for troubleshooting steps online',
                'Get current weather information'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded documents, files, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search'],
            examples=[
                'Search uploaded PDF for a keyword',
                'Find information in a user manual',
                'Extract data from a document'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this issue to a human expert',
                'I need to speak with a person',
                'Request human assistance for complex decision',
                'Connect me with a human agent'
            ],
        )
    ]

    # Create agent card
    agent_card = AgentCard(
        name='ServiceNow, Web & Knowledge Agent',
        description="An intelligent agent specialized in ServiceNow management, Bank system actions, web search, and file/knowledge/document search. Can simulate ServiceNow incidents, users, and knowledge base operations, perform any Bank action (block card, check balance, report fraud, etc.), search the web for current information, and search through uploaded documents/files for specific information, all with realistic synthetic responses.",
       # url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent1/',
        url=f'http://localhost:8000/',
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )

    # Create agent executor
    agent_executor_instance = create_foundry_agent_executor(agent_card)

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
    async def health_check(request: Request) -> PlainTextResponse:
        return PlainTextResponse('AI Foundry Expert Agent is running!')
    
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
            logger.info(f"🤝 Attempting to register '{agent_card.name}' with host agent...")
            registration_success = await register_with_host_agent(agent_card, host_url=CITIBANK_HOST_AGENT_URL)
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


async def get_foundry_response(
    message: str,
    history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    """Get response from Azure Foundry agent for Gradio UI."""
    global agent_executor_instance
    try:
        # Check if there are pending input_required tasks (user is responding to a request)
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            # Get the first pending task (in a real system, you might want to be more specific)
            context_id = next(iter(agent_executor_instance._waiting_for_input.keys()))
            request_text = agent_executor_instance._waiting_for_input[context_id]
            
            # If the user message is just checking for requests
            if message.lower().strip() in ["", "status", "check", "pending"] or len(message.strip()) == 0:
                yield gr.ChatMessage(
                    role="assistant",
                    content=f"🤖 **Pending Host Agent Request:**\n\n{request_text}\n\n*Please provide your expert response by typing your answer below.*"
                )
                return
            
            # This is the human expert's response
            yield gr.ChatMessage(
                role="assistant",
                content=f"✅ **Sending your response to Host Agent...**\n\nExpert Response: \"{message}\""
            )
            
            # Send the human response to complete the waiting task
            success = await agent_executor_instance.send_human_response(context_id, message)
            
            if success:
                yield gr.ChatMessage(
                    role="assistant",
                    content="✅ **Response sent successfully!** The Host Agent has received your expert input and will continue processing."
                )
                # Clear the pending request notification
                global pending_request_notification
                pending_request_notification = {"has_pending": False, "request_text": "", "context_id": ""}
            else:
                yield gr.ChatMessage(
                    role="assistant",
                    content="❌ **Error:** Could not send response to Host Agent. The task may have expired."
                )
            
            return
        
        # Regular foundry agent interaction
        # Get the shared agent that was initialized at startup
        foundry_agent = await FoundryAgentExecutor.get_shared_agent()
        
        if not foundry_agent:
            yield gr.ChatMessage(
                role="assistant",
                content="❌ Agent not initialized. Please restart the application.",
            )
            return
        
        # Create or reuse a thread for this conversation
        global ui_thread_id
        if not ui_thread_id:
            thread = await foundry_agent.create_thread()
            ui_thread_id = thread.id
        else:
            thread = await foundry_agent.create_thread(ui_thread_id)
        thread_id = ui_thread_id
        
        # Send a status update
        yield gr.ChatMessage(
            role="assistant",
            content="🤖 **Processing your request...**",
        )
        
        # Run the conversation using the streaming method
        response_count = 0
        async for response in foundry_agent.run_conversation_stream(thread_id, message):
            print("[DEBUG] get_foundry_response: response=", response)
            if isinstance(response, str):
                if response.strip():
                    # Filter out processing messages
                    if not any(phrase in response.lower() for phrase in [
                        "processing your request", "🤖 processing", "processing..."
                    ]):
                        yield gr.ChatMessage(role="assistant", content=response)
                        response_count += 1
            else:
                # handle other types if needed
                print(f"[DEBUG] get_foundry_response: Unexpected response type: {type(response)}")
                yield gr.ChatMessage(
                    role="assistant",
                    content=f"An error occurred while processing your request: {str(response)}. Please check the server logs for details.",
                )
                response_count += 1
        
        # If no responses were yielded, show a default message
        if response_count == 0:
            yield gr.ChatMessage(
                role="assistant", 
                content="I processed your request but didn't receive a response. Please try again."
            )
            
    except Exception as e:
        logger.error(f"Error in get_foundry_response (Type: {type(e)}): {e}")
        traceback.print_exc()
        yield gr.ChatMessage(
            role="assistant",
            content=f"An error occurred while processing your request: {str(e)}. Please check the server logs for details.",
        )


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
    print("🚀 Initializing AI Foundry agents at startup...")
    try:
        await initialize_foundry_agents_at_startup()
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agents at startup: {e}")
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
                id='salesforce_management',
                name='ServiceNow Management',
                description="Create, search, and manage ServiceNow incidents, users, and knowledge base articles. Simulates ServiceNow actions with realistic synthetic data.",
                tags=['servicenow', 'incident', 'it', 'support'],
                examples=[
                    'Create a new ServiceNow incident',
                    'Search for incidents assigned to a user',
                    'Update incident status',
                    'List ServiceNow users',
                    'Search ServiceNow knowledge base'
                ],
            ),
        AgentSkill(
            id='bank_actions',
            name='Bank Actions',
            description="Simulate any action on the Bank system (block card, check balance, report fraud, etc.) and return synthetic responses.",
            tags=['banking', 'finance', 'card'],
            examples=[
                'Block a credit card',
                'Check account balance',
                'Report a fraudulent transaction',
                'Simulate a generic Bank action'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for troubleshooting steps online',
                'Get current weather information'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded documents, files, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search'],
            examples=[
                'Search uploaded PDF for a keyword',
                'Find information in a user manual',
                'Extract data from a document'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this issue to a human expert',
                'I need to speak with a person',
                'Request human assistance for complex decision',
                'Connect me with a human agent'
            ],
        )
    ]

    agent_card = AgentCard(
        name='ServiceNow, Web & Knowledge Agent',
        description="An intelligent agent specialized in ServiceNow management, Bank system actions, web search, and file/knowledge/document search. Can simulate ServiceNow incidents, users, and knowledge base operations, perform any Bank action (block card, check balance, report fraud, etc.), search the web for current information, and search through uploaded documents/files for specific information, all with realistic synthetic responses.",
        #url=f'http://{host if host != "0.0.0.0" else DEFAULT_HOST}:{a2a_port}/',
        #url=f'https://agent1.ngrok.app/agent1/',
        url=f'http://localhost:8000/',
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
            print(f"[DEBUG] Full request text length: {len(request_text)}")
            print(f"[DEBUG] Request text preview: {request_text[:500]}...")
            
            # Extract conversation history - simplified approach
            conversation_entries: List[Dict[str, str]] = []
            
            # Look for the current request first
            current_request = ""
            if "Current request:" in request_text:
                current_request = request_text.split("Current request:", 1)[1].strip()
            
            # Extract simple conversation from the memory results
            if "Relevant context from previous interactions:" in request_text:
                import re
                
                # Find all the memory result entries
                # Pattern: "  {number}. From {agent_name}: {content}"
                memory_pattern = r'\s+(\d+)\.\s+From\s+([^:]+):\s+(.+?)(?=\n\s*\d+\.\s+From|\nCurrent request:|$)'
                matches = re.findall(memory_pattern, request_text, re.DOTALL)
                
                print(f"[DEBUG] Found {len(matches)} memory matches")
                
                for number, agent_name, content in matches:
                    # Clean up the agent name - keep original names
                    clean_agent_name = agent_name.strip()
                    
                    # Clean up the content
                    clean_content = content.strip()
                    
                    print(f"[DEBUG] Processing entry {number} from {clean_agent_name}: content_length={len(clean_content)}")
                    print(f"[DEBUG] Content preview: {clean_content[:100]}...")
                    
                    # Only skip entries that are PURELY technical JSON payloads with no readable content
                    # Be much less aggressive in filtering
                    if (clean_content.startswith('{') and 
                        len(clean_content) < 500 and  # Only skip short technical entries
                        all(tech_term in clean_content[:100] for tech_term in ['outbound_payload', 'configuration'])):
                        # This is a pure technical entry, skip it
                        print(f"[DEBUG] Skipping technical entry from {clean_agent_name}")
                        continue
                    
                    # For very long messages, try to extract readable parts, but keep more content
                    if len(clean_content) > 1000:
                        # Look for readable text patterns
                        
                        # First, try to find any text that looks like actual conversation
                        # Look for patterns like complete sentences or customer service language
                        readable_parts = []
                        
                        # Split by common delimiters and look for readable content
                        parts = re.split(r'[.!?]\s+', clean_content)
                        for part in parts:
                            part = part.strip()
                            if (part and len(part) > 20 and 
                                # Keep parts that look like actual conversation
                                (any(word in part.lower() for word in [
                                    'customer', 'account', 'card', 'fraud', 'help', 'assist', 
                                    'thank', 'please', 'sorry', 'issue', 'problem', 'service'
                                ]) or
                                # Or parts that don't have too much technical jargon
                                (part.count('"') < 3 and 
                                 not any(tech in part.lower() for tech in [
                                     'outbound_payload', 'inbound_payload', 'messageid', 'contextid'
                                 ])))):
                                readable_parts.append(part)
                        
                        if readable_parts:
                            # Take more readable parts (up to 5 instead of 3)
                            clean_content = '. '.join(readable_parts[:5]) + '.'
                        else:
                            # If no readable parts found, just truncate but keep more
                            clean_content = clean_content[:400] + '...'
                    
                    # Be much more inclusive - add almost everything that has some content
                    if clean_content and len(clean_content.strip()) > 3:
                        print(f"[DEBUG] Adding entry from {clean_agent_name}: {clean_content[:50]}...")
                        conversation_entries.append({
                            "role": clean_agent_name,
                            "text": clean_content.strip()
                        })
                    else:
                        print(f"[DEBUG] Rejecting entry from {clean_agent_name}: too short or empty")
            print(f"[DEBUG] Extracted {len(conversation_entries)} conversation entries")

            if not conversation_entries:
                conversation_entries.append({
                    "role": "System",
                    "text": "No prior conversation history was provided with this escalation."
                })

            # Show all conversation entries (no limit)
            # conversation_entries = conversation_entries[-20:]  # Removed limit to show full history

            def format_message_content(text: str) -> str:
                if not text:
                    return (
                        "<span style=\"opacity: 1.0; color: #1f2937; font-style: italic;\">"
                        "No message content provided." "</span>"
                    )

                # Just return the text as-is, properly escaped
                # The extraction logic above already handles cleaning up the content
                return html.escape(text.strip()).replace("\n", "<br/>")

            role_styles = {
                "user": {
                    "label": "Customer",
                    "justify": "flex-start",
                    "bg": "#f8fafc",
                    "color": "#0f172a",
                    "radius": "16px 16px 16px 4px",
                    "border": "1px solid rgba(148, 163, 184, 0.35)",
                    "shadow": "0 6px 16px rgba(15, 23, 42, 0.18)",
                    "text_align": "left",
                },
                "customer": {
                    "label": "Customer",
                    "justify": "flex-start",
                    "bg": "#f8fafc",
                    "color": "#0f172a",
                    "radius": "16px 16px 16px 4px",
                    "border": "1px solid rgba(148, 163, 184, 0.35)",
                    "shadow": "0 6px 16px rgba(15, 23, 42, 0.18)",
                    "text_align": "left",
                },
                "host_agent": {
                    "label": "host_agent",
                    "justify": "flex-end",
                    "bg": "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                    "color": "#f8fafc",
                    "radius": "16px 16px 4px 16px",
                    "border": "1px solid rgba(59, 130, 246, 0.4)",
                    "shadow": "0 6px 18px rgba(37, 99, 235, 0.35)",
                    "text_align": "left",
                },
                "assistant": {
                    "label": "Assistant",
                    "justify": "flex-end",
                    "bg": "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                    "color": "#f8fafc",
                    "radius": "16px 16px 4px 16px",
                    "border": "1px solid rgba(59, 130, 246, 0.4)",
                    "shadow": "0 6px 18px rgba(37, 99, 235, 0.35)",
                    "text_align": "left",
                },
                "agent": {
                    "label": "Agent",
                    "justify": "flex-end",
                    "bg": "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                    "color": "#f8fafc",
                    "radius": "16px 16px 4px 16px",
                    "border": "1px solid rgba(59, 130, 246, 0.4)",
                    "shadow": "0 6px 18px rgba(37, 99, 235, 0.35)",
                    "text_align": "left",
                },
                "system": {
                    "label": "System",
                    "justify": "center",
                    "bg": "rgba(148, 163, 184, 0.25)",
                    "color": "#e2e8f0",
                    "radius": "14px",
                    "border": "1px solid rgba(148, 163, 184, 0.35)",
                    "shadow": "0 4px 14px rgba(15, 23, 42, 0.25)",
                    "text_align": "center",
                },
                "payload": {
                    "label": "Context Payload",
                    "justify": "flex-start",
                    "bg": "rgba(30, 41, 59, 0.6)",
                    "color": "#f8fafc",
                    "radius": "16px",
                    "border": "1px solid rgba(148, 163, 184, 0.4)",
                    "shadow": "0 6px 16px rgba(15, 23, 42, 0.3)",
                    "text_align": "left",
                },
                "default": {
                    "label": None,
                    "justify": "flex-start",
                    "bg": "rgba(148, 163, 184, 0.2)",
                    "color": "#f8fafc",
                    "radius": "16px",
                    "border": "1px solid rgba(148, 163, 184, 0.35)",
                    "shadow": "0 4px 12px rgba(15, 23, 42, 0.25)",
                    "text_align": "left",
                },
            }

            participants: set[str] = set()
            message_blocks: list[str] = []

            for idx, entry in enumerate(conversation_entries, start=1):
                role = entry.get("role", "Participant")
                role_key = role.lower()
                style = role_styles.get(role_key, role_styles["default"])
                label_text = style.get("label") or (role.title() if role else "Participant")
                participants.add(label_text)

                bubble_style = (
                    f"background: {style['bg']}; "
                    f"color: {style['color']}; "
                    "padding: 12px 14px; "
                    f"border-radius: {style['radius']}; "
                    f"border: {style['border']}; "
                    f"box-shadow: {style['shadow']}; "
                    "max-width: 85%; "
                    "backdrop-filter: blur(4px); "
                    "font-family: 'Inter', 'Segoe UI', sans-serif; "
                )

                text_align = style.get("text_align", "left")
                content_html = format_message_content(entry.get("text", ""))

                message_block = (
                    f'<div style="display:flex; justify-content: {style["justify"]};">'
                    f'<div style="{bubble_style}">'
                    '<div style="display:flex; justify-content: space-between; align-items: center; '
                    'font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; opacity: 1.0;">'
                    f'<span>{html.escape(label_text)}</span>'
                    f'<span style="font-weight: 600; opacity: 1.0;">#{idx}</span>'
                    '</div>'
                    f'<div style="margin-top: 8px; font-size: 14px; line-height: 1.55; text-align: {text_align};">'
                    f'{content_html}'
                    '</div>'
                    '</div>'
                    '</div>'
                )

                message_blocks.append(message_block)

            if message_blocks:
                conversation_html = "".join(message_blocks)
            else:
                conversation_html = (
                    "<div style=\"font-style: italic; opacity: 1.0; color: #1f2937;\">"
                    "No conversation history available." "</div>"
                )

            participants_display = ""
            if participants:
                sorted_participants = ", ".join(sorted(participants))
                participants_display = (
                    f'<div style="font-size: 12px; opacity: 1.0; color: #1f2937; margin-bottom: 10px;">'
                    f'Participants: {html.escape(sorted_participants)}'
                    '</div>'
                )

            history_count = len(conversation_entries)
            history_label = "message" if history_count == 1 else "messages"

            # Extract the current request (already done above)
            current_request_html = ""
            if current_request:
                formatted_request = format_message_content(current_request)
                current_request_html = (
                    '<div style="margin-top: 16px; padding: 16px; background: rgba(30, 64, 175, 0.25); '
                    'border-radius: 12px; border: 1px solid rgba(59, 130, 246, 0.35);">'
                    '<div style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; '
                    'opacity: 1.0; color: #1f2937; margin-bottom: 6px;">Current Request</div>'
                    f'<div style="font-size: 14px; line-height: 1.55;">{formatted_request}</div>'
                    '</div>'
                )

            # Display the conversation history
            return (
                f"<div style=\"background: linear-gradient(135deg, #0f172a 0%, #1f2937 100%); "
                "color: #f8fafc; padding: 24px; border-radius: 16px; margin: 12px 0; "
                "box-shadow: 0 16px 32px rgba(15, 23, 42, 0.45); "
                "font-family: 'Inter', 'Segoe UI', sans-serif;\">"
                "<h2 style=\"margin: 0 0 18px; color: #f8fafc;\">🚨 Escalation: Pending Support Intervention</h2>"
                "<div style=\"background: rgba(15, 23, 42, 0.6); padding: 18px; border-radius: 12px; "
                "border: 1px solid rgba(148, 163, 184, 0.25);\">"
                "<div style=\"display:flex; justify-content: space-between; align-items: center; "
                "margin-bottom: 12px;\">"
                f"<span style=\"font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; "
                "opacity: 1.0; color: #f8fafc;\">Conversation History</span>"
                f"<span style=\"font-size: 12px; opacity: 1.0; color: #f8fafc;\">Last {history_count} {history_label}</span>"
                "</div>"
                f"{participants_display}"
                "<div style=\"max-height: 600px; overflow-y: auto; display: flex; flex-direction: column; "
                "gap: 12px; padding-right: 6px;\">"
                f"{conversation_html}"
                "</div>"
                "</div>"
                f"{current_request_html}"
                "<div style=\"margin-top: 16px; padding: 12px; background: rgba(59, 130, 246, 0.15); "
                "border-radius: 8px; text-align: center; border: 1px solid rgba(59, 130, 246, 0.25);\">"
                "<strong>⏰ Action Required:</strong> Please respond via the chat below to assist the requester."
                "</div>"
                "</div>"
            )
        return """
<div style="background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: white; padding: 15px; border-radius: 8px; margin: 10px 0; text-align: center;">
<h3 style="margin: 0; color: white;">✅ Status: No pending requests - Ready for new expert consultations</h3>
</div>
"""

    # Create dashboard instance
    dashboard = SupportDashboard()
    
    def format_customer_info(customer):
        """Format customer information for display"""
        # Set risk level icon based on value
        if customer['risk_level'] == 'Low':
            risk_icon = '🟢'
        elif customer['risk_level'] == 'Medium':
            risk_icon = '🟡'
        else:  # High
            risk_icon = '🔴'
            
        return f"""
**Customer ID:** {customer['customer_id']}  
**Name:** {customer['name']}  
**Phone:** {customer['phone']}  
**Email:** [{customer['email']}](mailto:{customer['email']})  
**Member Since:** {customer['join_date']}  
**Tier:** {customer['customer_tier']}  
**Relationship Manager:** {customer['relationship_manager']}  
**Last Login:** {customer['last_login']}  
**Auth Status:** ✅ {customer['authentication_status']}  
**Risk Level:** {risk_icon} {customer['risk_level']}
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
    
    def refresh_customer_data():
        """Refresh customer information display"""
        global agent_executor_instance
        
        # Check if there are pending requests and switch profiles accordingly
        if agent_executor_instance and agent_executor_instance._waiting_for_input:
            dashboard.switch_to_david_miller()
        else:
            dashboard.switch_to_ana_lucia()
        
        data = dashboard.get_dashboard_data()
        return (
            format_customer_info(data["customer"]),
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
    .customer-info {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        color: #1f2937 !important;
        font-weight: 500;
    }
    .customer-info p {
        color: #1f2937 !important;
        margin: 8px 0;
        line-height: 1.5;
    }
    .customer-info strong {
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

    with gr.Blocks(css=dashboard_css, theme=gr.themes.Ocean(), title="Customer Support Dashboard - AI Foundry Expert Agent") as demo:
        
        # Dashboard Header
        gr.HTML(f"""
        <div class="dashboard-header">
            <div style="display: flex; align-items: center; justify-content: center; gap: 15px;">
                <div>
                    <h1 style="margin: 0;">Customer Support Agent (A2A)</h1>
                    <h3 style="margin: 5px 0;">An intelligent Azure Foundry agent specialized in ServiceNow (MCP) management, system actions, web search, and file/knowledge/document search.</h3>
                    <p style="margin: 5px 0;">Agent Workstation | Session: Active | Time: <span id="current-time"></span></p>
                    <p style="margin: 5px 0;"><strong>Direct UI Access:</strong> http://localhost:{ui_port} | <strong>A2A API Access:</strong> http://localhost:{a2a_port}</p>
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
        refresh_timer = gr.HTML("""
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

        def _append_chat_notification(history: List[dict], message: str) -> List[dict]:
            history = history or []
            new_history = list(history)
            new_history.append({"role": "assistant", "content": message})
            return new_history

        def notify_freeze_account(history: List[dict]) -> List[dict]:
            return _append_chat_notification(history, "✅ **Freeze account command executed.** The account has been frozen as requested.")

        def notify_order_card(history: List[dict]) -> List[dict]:
            return _append_chat_notification(history, "✅ **Order card command executed.** A replacement card order has been submitted.")

        with gr.Row():
            gr.Button("🔒 Reset Password", size="sm")
            gr.Button("❄️ Freeze Account", size="sm").click(
                notify_freeze_account,
                inputs=[chatbot_interface],
                outputs=chatbot_interface,
            )
            gr.Button("💳 Order Card", size="sm").click(
                notify_order_card,
                inputs=[chatbot_interface],
                outputs=chatbot_interface,
            )
            gr.Button("📧 Send Email", size="sm")
        
        # Customer Information and Account Details Section
        with gr.Row():
            # Left Panel - Customer Information, Accounts, Tickets, Transactions
            with gr.Column(scale=1):
                gr.Markdown("### 👤 Customer Information")
                customer_info = gr.Markdown(
                    format_customer_info(dashboard.current_customer),
                    elem_classes=["customer-info"]
                )
                
                gr.Markdown("### 💳 Account Overview")
                accounts_table = gr.Dataframe(
                    value=format_accounts_table(dashboard.accounts),
                    headers=["Account Type", "Number", "Balance", "Status", "Last Transaction"],
                    interactive=False
                )
                
                gr.Markdown("### 🎫 Open ServiceNow Incidents")
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
                gr.Markdown("### 📊 Customer Analytics & Services")
                customer_analytics = gr.HTML(value=dashboard.get_customer_analytics())

        
        # Agent Tools Panel
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🛠️ Agent Tools")
                with gr.Row():
                    gr.Button("📊 Generate Report", variant="secondary")
                    gr.Button("📞 Schedule Callback", variant="secondary")
                    gr.Button("✉️ Send Secure Message", variant="secondary")
                    gr.Button("🔄 Refresh Data", variant="secondary").click(
                        refresh_customer_data,
                        outputs=[customer_info, accounts_table, tickets_table, transactions_table, customer_analytics]
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
                r'\bticket\s+\d+',  # Match "ticket" followed by numbers (explicit dashboard intent)
                r'\baccount\s+balance\b',
                r'\bescalate\b',
                r'\blogin\s+issue\b',
                r'\bpassword\s+reset\b',
                r'\bcredit\s+limit\b'
            ]
            
            is_dashboard_query = any(re.search(pattern, query_lower) for pattern in dashboard_patterns)
            # Never intercept ServiceNow record lookups by ID; let the Foundry agent handle INC/REQ/CHG/PRB
            if re.search(r'\b(?:inc|req|chg|prb)\d{6,}\b', message, re.IGNORECASE):
                is_dashboard_query = False
            
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
                    foundry_agent = await FoundryAgentExecutor.get_shared_agent()
                    
                    if not foundry_agent:
                        history.append({"role": "assistant", "content": "❌ Agent not initialized. Please restart the application."})
                        return "", history
                    
                    # Create or reuse a thread for this conversation
                    global ui_thread_id
                    if not ui_thread_id:
                        thread = await foundry_agent.create_thread()
                        ui_thread_id = thread.id
                    else:
                        thread = await foundry_agent.create_thread(ui_thread_id)
                    thread_id = ui_thread_id
                    
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
            """Combined refresh for both status and customer data"""
            global agent_executor_instance
            
            # Check if there are pending requests and switch profiles accordingly
            if agent_executor_instance and agent_executor_instance._waiting_for_input:
                dashboard.switch_to_david_miller()
            else:
                dashboard.switch_to_ana_lucia()
            
            data = dashboard.get_dashboard_data()
            return (
                check_pending_requests(),
                format_customer_info(data["customer"]),
                format_accounts_table(data["accounts"]),
                format_tickets_table(data["tickets"]),
                format_transactions_table(data["transactions"]),
                data["analytics"]
            )
        
        timer.tick(fn=combined_refresh, outputs=[status_display, customer_info, accounts_table, tickets_table, transactions_table, customer_analytics])

        # Optional: Reset conversation button to clear thread and chat history
        def reset_conversation():
            global ui_thread_id
            ui_thread_id = None
            return []

        gr.Button("🗑️ Reset Chat", variant="secondary").click(
            reset_conversation,
            outputs=chatbot_interface
        )

    print(f"Launching AI Foundry Expert Agent Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("AI Foundry Expert Agent Gradio application has been shut down.")


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
    print("🚀 Initializing AI Foundry agents at startup...")
    try:
        await initialize_foundry_agents_at_startup()
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agents at startup: {e}")
        raise

    print(f"Starting AI Foundry Expert Agent A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Create agent card for registration
    skills = [
        AgentSkill(
            id='salesforce_management',
            name='ServiceNow Management',
            description="Create, search, and manage ServiceNow incidents, users, and knowledge base articles. Simulates ServiceNow actions with realistic synthetic data.",
            tags=['servicenow', 'incident', 'it', 'support'],
            examples=[
                'Create a new ServiceNow incident',
                'Search for incidents assigned to a user',
                'Update incident status',
                'List ServiceNow users',
                'Search ServiceNow knowledge base'
            ],
        ),
        AgentSkill(
            id='bank_actions',
            name='Bank Actions',
            description="Simulate any action on the Bank system (block/unblock card, check balance, report fraud, create disputes, issue refunds, etc.) and return synthetic responses.",
            tags=['banking', 'finance', 'card', 'dispute', 'refund'],
            examples=[
                'Block a credit card',
                'Unblock a credit card',
                'Check account balance',
                'Report a fraudulent transaction',
                'Create a dispute for a transaction',
                'Issue a refund for a transaction',
                'Check transaction details'
            ],
        ),
        AgentSkill(
            id='web_search',
            name='Web Search',
            description="Search the web for current information using Bing or other integrated search tools.",
            tags=['web', 'search', 'bing', 'internet'],
            examples=[
                'Find the latest news about a company',
                'Search for troubleshooting steps online',
                'Get current weather information'
            ],
        ),
        AgentSkill(
            id='file_knowledge_search',
            name='File & Knowledge Search',
            description="Search through uploaded documents, files, and knowledge bases for specific information.",
            tags=['file', 'document', 'knowledge', 'search'],
            examples=[
                'Search uploaded PDF for a keyword',
                'Find information in a user manual',
                'Extract data from a document'
            ],
        ),
        AgentSkill(
            id='human_interaction',
            name='Human Expert Escalation',
            description="Escalate complex issues to human experts or facilitate human-in-the-loop interactions when automated responses are insufficient.",
            tags=['human-interaction', 'escalation', 'expert', 'human-capable'],
            examples=[
                'Escalate this issue to a human expert',
                'I need to speak with a person',
                'Request human assistance for complex decision',
                'Connect me with a human agent'
            ],
        )
    ]

    agent_card = AgentCard(
        name='ServiceNow, Web & Knowledge Agent',
        description="An intelligent agent specialized in ServiceNow management, Bank system actions, web search, and file/knowledge/document search. Can simulate ServiceNow incidents, users, and knowledge base operations, perform any Bank action (block card, check balance, report fraud, etc.), search the web for current information, and search through uploaded documents/files for specific information, all with realistic synthetic responses.",
        #url=f'http://{host}:{port}/',
        #url=f'https://agent1.ngrok.app/agent1/',
        url=f'http://localhost:8000/',
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=skills,
    )
    
    # Start background registration
    start_background_registration(agent_card)
    
    # Use uvicorn server directly instead of uvicorn.run() to avoid event loop conflicts
    import uvicorn.server
    config = uvicorn.Config(app, host=host, port=port)
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
    """AI Foundry Expert Agent - can run as A2A server or with Gradio UI + A2A server."""
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
