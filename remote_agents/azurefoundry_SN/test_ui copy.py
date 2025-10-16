import gradio as gr
import json
import datetime
import random
import re
from typing import Dict, List, Tuple, Optional
import pandas as pd
import base64

# Convert Citi logo to base64
def get_citi_logo_base64():
    try:
        with open("Citi_logo.png", "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
            return f"data:image/png;base64,{encoded_string}"
    except:
        return None

# Get the base64 logo
citi_logo_base64 = get_citi_logo_base64()

class CitibankSupportDashboard:
    def __init__(self):
        # Mock customer data
        self.current_customer = {
            "customer_id": "CITI789456123",
            "name": "David Miller",
            "phone": "+1 (555) 123-4567",
            "email": "david.miller@email.com",
            "join_date": "March 15, 2019",
            "customer_tier": "Citi Priority",
            "relationship_manager": "Michael Chen",
            "last_login": "January 15, 2024 - 2:30 PM EST",
            "authentication_status": "Verified",
            "risk_level": "Low"
        }
        
        # Account information
        self.accounts = [
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

    def get_dashboard_data(self):
        """Return all dashboard data for display"""
        return {
            "customer": self.current_customer,
            "accounts": self.accounts,
            "tickets": self.open_tickets,
            "transactions": self.recent_transactions
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
        return """**🏦 Welcome to Citibank Support Dashboard**

I'm here to help you with customer support tasks. You can:

• Ask about specific tickets (e.g., "INC0012345")
• Request account summaries
• Get escalation options
• Search the knowledge base

How can I assist you today?"""

def create_citibank_dashboard():
    """Create the comprehensive Citibank support dashboard"""
    
    dashboard = CitibankSupportDashboard()
    
    def chat_response(message: str, history: List[dict]) -> Tuple[str, List[dict]]:
        """Process agent chat messages"""
        if not message.strip():
            return "", history
        
        response = dashboard.process_agent_query(message)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
        return "", history
    
    def refresh_customer_data():
        """Refresh customer information display"""
        data = dashboard.get_dashboard_data()
        return (
            format_customer_info(data["customer"]),
            format_accounts_table(data["accounts"]),
            format_tickets_table(data["tickets"]),
            format_transactions_table(data["transactions"])
        )
    
    def format_customer_info(customer):
        """Format customer information for display"""
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
**Risk Level:** 🟢 {customer['risk_level']}
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
    
    # Custom CSS for Citibank dashboard styling
    dashboard_css = """
    .gradio-container {
        max-width: 1400px !important;
        margin: auto !important;
    }
    .dashboard-header {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
        color: white;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 20px;
        text-align: center;
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
    
    # Create the dashboard interface
    with gr.Blocks(css=dashboard_css, title="Citibank Support Dashboard") as interface:
        
        # Dashboard Header
        gr.HTML(f"""
        <div class="dashboard-header">
            <div style="display: flex; align-items: center; justify-content: center; gap: 15px;">
                <img src="{citi_logo_base64 or ''}" alt="Citi Logo" style="height: 40px; width: auto;">
                <div>
                    <h1 style="margin: 0;">Citibank Customer Support Agent (A2A)</h1>
                    <h3 style="margin: 5px 0;">An intelligent Azure Foundryagent specialized in ServiceNow (MCP) management, system actions, web search, and file/knowledge/document search. </h3>
                    <p style="margin: 5px 0;">Agent Workstation | Session: Active | Time: <span id="current-time"></span></p>
                </div>
            </div>
        </div>
        """)
        
        # Main dashboard layout
        with gr.Row():
            # Left Panel - Customer Information
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
                
                # Quick Actions
                gr.Markdown("### ⚡ Quick Actions")
                with gr.Row():
                    gr.Button("🔒 Reset Password", size="sm")
                    gr.Button("❄️ Freeze Account", size="sm")
                with gr.Row():
                    gr.Button("💳 Order Card", size="sm")
                    gr.Button("📧 Send Email", size="sm")
            
            # Center Panel - Chat Interface
            with gr.Column(scale=2):
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
                    gr.Button("🎫 View Tickets", size="sm").click(
                        lambda: ("show all open tickets", []),
                        outputs=[agent_input, chatbot_interface]
                    )
                    gr.Button("💰 Account Summary", size="sm").click(
                        lambda: ("account summary", []),
                        outputs=[agent_input, chatbot_interface]
                    )
                    gr.Button("🔺 Escalate", size="sm").click(
                        lambda: ("escalation options", []),
                        outputs=[agent_input, chatbot_interface]
                    )
                    gr.Button("📋 Knowledge Base", size="sm").click(
                        lambda: ("search knowledge base", []),
                        outputs=[agent_input, chatbot_interface]
                    )
        
        # Bottom Panel - Tickets and Transactions
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🎫 Open ServiceNow Tickets")
                tickets_table = gr.Dataframe(
                    value=format_tickets_table(dashboard.open_tickets),
                    headers=["Ticket ID", "Priority", "Status", "Subject", "Created", "Assigned To", "Last Update", "Description", "Resolution Time"],
                    interactive=False
                )
            
            with gr.Column():
                gr.Markdown("### 💸 Recent Transactions")
                transactions_table = gr.Dataframe(
                    value=format_transactions_table(dashboard.recent_transactions),
                    headers=["Date", "Description", "Amount", "Account"],
                    interactive=False
                )
        
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
                        outputs=[customer_info, accounts_table, tickets_table, transactions_table]
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
        
        # Event handlers
        send_btn.click(
            chat_response,
            inputs=[agent_input, chatbot_interface],
            outputs=[agent_input, chatbot_interface]
        )
        
        agent_input.submit(
            chat_response,
            inputs=[agent_input, chatbot_interface],
            outputs=[agent_input, chatbot_interface]
        )
    
    return interface

# Launch the Citibank support dashboard
if __name__ == "__main__":
    interface = create_citibank_dashboard()
    interface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=True,
        show_error=True,
        debug=True,
        favicon_path="Citi_logo.png"
    )
