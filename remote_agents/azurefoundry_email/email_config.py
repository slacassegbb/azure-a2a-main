"""
Email Agent Configuration
=========================

Configuration for the Email Agent that sends emails via Microsoft Graph API.
Credentials are loaded from environment variables.
"""
import os
import logging
import requests
from dotenv import load_dotenv
from azure.identity import ClientSecretCredential

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)

# ===========================
# COMPANY INFORMATION  
# ===========================

COMPANY_NAME = "AI Consulting Solutions"
COMPANY_DESCRIPTION = "a leading AI consulting firm specializing in enterprise AI implementation"
AGENT_ROLE = "Email Communications Specialist"

# ===========================
# EMAIL CONFIGURATION
# ===========================

def get_email_credentials():
    """
    Get email credentials from environment variables.
    Supports both EMAIL_* prefixed names and non-prefixed names for flexibility.
    """
    # Try EMAIL_* prefix first, fall back to non-prefixed names
    tenant_id = os.getenv("EMAIL_TENANT_ID") or os.getenv("TENANT_ID", "")
    client_id = os.getenv("EMAIL_CLIENT_ID") or os.getenv("CLIENT_ID", "")
    client_secret = os.getenv("EMAIL_CLIENT_SECRET") or os.getenv("CLIENT_SECRET", "")
    sender_email = os.getenv("EMAIL_SENDER_ADDRESS") or os.getenv("SENDER_EMAIL", "")
    
    # Log what we found (without exposing secrets)
    logger.info(f"Email credentials loaded: tenant_id={'set' if tenant_id else 'MISSING'}, "
                f"client_id={'set' if client_id else 'MISSING'}, "
                f"client_secret={'set' if client_secret else 'MISSING'}, "
                f"sender_email={sender_email if sender_email else 'MISSING'}")
    
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "sender_email": sender_email,
    }


def send_email(
    to: str, 
    subject: str, 
    body: str, 
    content_type: str = "HTML",
    attachments: list = None
) -> dict:
    """
    Send an email using Microsoft Graph API with application permissions.
    
    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body content (HTML or plain text)
        content_type: "HTML" or "Text" (default: "HTML")
        attachments: Optional list of attachment dicts with keys:
                     - 'path': file path to attach
                     - 'name': optional display name (defaults to filename)
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    import base64
    
    credentials = get_email_credentials()
    
    # Validate credentials with helpful error messages
    if not credentials["tenant_id"]:
        logger.error("Missing tenant_id - set EMAIL_TENANT_ID or TENANT_ID in .env")
        return {"success": False, "message": "Missing EMAIL_TENANT_ID or TENANT_ID environment variable"}
    if not credentials["client_id"]:
        logger.error("Missing client_id - set EMAIL_CLIENT_ID or CLIENT_ID in .env")
        return {"success": False, "message": "Missing EMAIL_CLIENT_ID or CLIENT_ID environment variable"}
    if not credentials["client_secret"]:
        logger.error("Missing client_secret - set EMAIL_CLIENT_SECRET or CLIENT_SECRET in .env")
        return {"success": False, "message": "Missing EMAIL_CLIENT_SECRET or CLIENT_SECRET environment variable"}
    if not credentials["sender_email"]:
        logger.error("Missing sender_email - set EMAIL_SENDER_ADDRESS or SENDER_EMAIL in .env")
        return {"success": False, "message": "Missing EMAIL_SENDER_ADDRESS or SENDER_EMAIL environment variable"}
    
    # Validate recipient
    if not to or "@" not in to:
        return {"success": False, "message": f"Invalid recipient email address: {to}"}
    
    try:
        # Get OAuth token
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        # Prepare the Graph API request
        url = f"https://graph.microsoft.com/v1.0/users/{credentials['sender_email']}/sendMail"
        
        message = {
            "subject": subject,
            "body": {
                "contentType": content_type,
                "content": body,
            },
            "toRecipients": [
                {"emailAddress": {"address": to}}
            ],
        }
        
        # Add attachments if provided
        if attachments:
            message["attachments"] = []
            for attachment in attachments:
                file_path = attachment.get("path")
                if file_path and os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        file_content = base64.b64encode(f.read()).decode("utf-8")
                    
                    file_name = attachment.get("name") or os.path.basename(file_path)
                    
                    # Determine content type
                    if file_path.endswith(".pdf"):
                        content_type_attach = "application/pdf"
                    elif file_path.endswith(".png"):
                        content_type_attach = "image/png"
                    elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                        content_type_attach = "image/jpeg"
                    else:
                        content_type_attach = "application/octet-stream"
                    
                    message["attachments"].append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": file_name,
                        "contentType": content_type_attach,
                        "contentBytes": file_content,
                    })
                    logger.info(f"Added attachment: {file_name}")
        
        payload = {
            "message": message,
            "saveToSentItems": True,
        }
        
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,  # Longer timeout for attachments
        )
        
        if response.status_code >= 300:
            error_msg = f"Email send failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
        
        attachment_info = f" with {len(attachments)} attachment(s)" if attachments else ""
        logger.info(f"Email sent successfully to {to}{attachment_info}")
        return {"success": True, "message": f"Email sent successfully to {to}{attachment_info}"}
        
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg}


def send_email_with_cc(
    to: str, 
    subject: str, 
    body: str, 
    cc: list = None,
    content_type: str = "HTML",
    attachments: list = None
) -> dict:
    """
    Send an email with CC recipients using Microsoft Graph API.
    
    Args:
        to: Primary recipient email address
        subject: Email subject line
        body: Email body content (HTML or plain text)
        cc: List of CC email addresses (optional)
        content_type: "HTML" or "Text" (default: "HTML")
        attachments: Optional list of attachment dicts with keys:
                     - 'path': file path to attach
                     - 'name': optional display name (defaults to filename)
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    import base64
    
    credentials = get_email_credentials()
    
    # Validate credentials
    if not all([credentials["tenant_id"], credentials["client_id"], 
                credentials["client_secret"], credentials["sender_email"]]):
        return {"success": False, "message": "Missing email credentials in environment variables"}
    
    if not to or "@" not in to:
        return {"success": False, "message": f"Invalid recipient email address: {to}"}
    
    try:
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        url = f"https://graph.microsoft.com/v1.0/users/{credentials['sender_email']}/sendMail"
        
        message = {
            "subject": subject,
            "body": {
                "contentType": content_type,
                "content": body,
            },
            "toRecipients": [
                {"emailAddress": {"address": to}}
            ],
        }
        
        # Add CC recipients if provided
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": email}} for email in cc if "@" in email
            ]
        
        # Add attachments if provided
        if attachments:
            message["attachments"] = []
            for attachment in attachments:
                file_path = attachment.get("path")
                if file_path and os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        file_content = base64.b64encode(f.read()).decode("utf-8")
                    
                    file_name = attachment.get("name") or os.path.basename(file_path)
                    
                    if file_path.endswith(".pdf"):
                        content_type_attach = "application/pdf"
                    elif file_path.endswith(".png"):
                        content_type_attach = "image/png"
                    else:
                        content_type_attach = "application/octet-stream"
                    
                    message["attachments"].append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": file_name,
                        "contentType": content_type_attach,
                        "contentBytes": file_content,
                    })
        
        payload = {
            "message": message,
            "saveToSentItems": True,
        }
        
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        
        if response.status_code >= 300:
            error_msg = f"Email send failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
        
        cc_info = f" (CC: {', '.join(cc)})" if cc else ""
        attachment_info = f" with {len(attachments)} attachment(s)" if attachments else ""
        logger.info(f"Email sent successfully to {to}{cc_info}{attachment_info}")
        return {"success": True, "message": f"Email sent successfully to {to}{cc_info}{attachment_info}"}
        
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg}


# ===========================
# EMAIL TEMPLATES
# ===========================

EMAIL_TEMPLATES = {
    "welcome": {
        "subject": "Welcome to {company_name}!",
        "body": """
<h1>Welcome!</h1>
<p>Hi {recipient_name},</p>
<p>Thank you for your interest in {company_name}. We're excited to connect with you!</p>
<p>Best regards,<br>The {company_name} Team</p>
"""
    },
    "follow_up": {
        "subject": "Following up on our conversation",
        "body": """
<p>Hi {recipient_name},</p>
<p>Thank you for taking the time to speak with us about {topic}.</p>
<p>{custom_message}</p>
<p>Best regards,<br>{sender_name}</p>
"""
    },
    "report": {
        "subject": "Your AI Consultation Report",
        "body": """
<h1>AI Consultation Report</h1>
<p>Hi {recipient_name},</p>
<p>As promised, here's your personalized AI consultation report.</p>
<h2>Your Use Case</h2>
<p>{use_case}</p>
<h2>Our Recommendations</h2>
<p>{recommendations}</p>
<h2>Next Steps</h2>
<p>{next_steps}</p>
<p>Best regards,<br>The {company_name} Team</p>
"""
    }
}


def get_template(template_name: str) -> dict:
    """Get an email template by name."""
    return EMAIL_TEMPLATES.get(template_name, {})


def format_template(template_name: str, **kwargs) -> dict:
    """
    Format an email template with provided variables.
    
    Returns:
        dict with 'subject' and 'body' keys, or empty dict if template not found
    """
    template = get_template(template_name)
    if not template:
        return {}
    
    # Add company name as default
    kwargs.setdefault("company_name", COMPANY_NAME)
    
    try:
        return {
            "subject": template["subject"].format(**kwargs),
            "body": template["body"].format(**kwargs),
        }
    except KeyError as e:
        logger.warning(f"Missing template variable: {e}")
        return template  # Return unformatted template

