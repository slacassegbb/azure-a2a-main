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


# ===========================
# EMAIL READING/FETCHING
# ===========================

def get_emails(
    count: int = 10,
    unread_only: bool = False,
    from_address: str = None,
    subject_contains: str = None,
    since_date: str = None,
    folder: str = "inbox"
) -> dict:
    """
    Fetch emails from the inbox using Microsoft Graph API.
    
    Args:
        count: Number of emails to retrieve (default: 10, max: 50)
        unread_only: If True, only fetch unread emails
        from_address: Filter by sender email address (partial match)
        subject_contains: Filter by subject line (partial match)
        since_date: Only get emails after this date (ISO format: 2026-02-04)
        folder: Mail folder to read from (default: "inbox")
    
    Returns:
        dict with 'success' (bool), 'message' (str), and 'emails' (list)
    """
    credentials = get_email_credentials()
    
    # Validate credentials
    if not all([credentials["tenant_id"], credentials["client_id"], 
                credentials["client_secret"], credentials["sender_email"]]):
        return {"success": False, "message": "Missing email credentials", "emails": []}
    
    try:
        # Get OAuth token
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        # Build the Graph API URL with filters
        user_email = credentials["sender_email"]
        count = min(count, 50)  # Cap at 50
        
        # Build filter query
        filters = []
        if unread_only:
            filters.append("isRead eq false")
        if since_date:
            filters.append(f"receivedDateTime ge {since_date}T00:00:00Z")
        
        # Construct URL - use /messages directly for broader compatibility
        # The /mailFolders/inbox/messages path can have issues with some mailbox configurations
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages"
        params = {
            "$top": count,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,body,hasAttachments,toRecipients,ccRecipients,parentFolderId"
        }
        
        # Add folder filter if not inbox (inbox is default for /messages)
        if folder and folder.lower() != "inbox":
            # For specific folders, we need to use the mailFolders endpoint
            url = f"https://graph.microsoft.com/v1.0/users/{user_email}/mailFolders/{folder}/messages"
        
        if filters:
            params["$filter"] = " and ".join(filters)
        
        logger.info(f"Fetching emails from: {url}")
        logger.info(f"Query params: {params}")
        
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            params=params,
            timeout=30,
        )
        
        logger.info(f"Response status: {response.status_code}")
        
        if response.status_code >= 300:
            error_msg = f"Failed to fetch emails: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg, "emails": []}
        
        data = response.json()
        messages = data.get("value", [])
        
        logger.info(f"API returned {len(messages)} messages")
        
        # Apply client-side filters for partial matches (Graph doesn't support contains on all fields)
        filtered_messages = []
        for msg in messages:
            # Filter by sender
            if from_address:
                sender_email = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower()
                sender_name = msg.get("from", {}).get("emailAddress", {}).get("name", "").lower()
                if from_address.lower() not in sender_email and from_address.lower() not in sender_name:
                    continue
            
            # Filter by subject
            if subject_contains:
                subject = msg.get("subject", "").lower()
                if subject_contains.lower() not in subject:
                    continue
            
            filtered_messages.append(msg)
        
        # Format the emails for response
        emails = []
        for msg in filtered_messages:
            from_info = msg.get("from", {}).get("emailAddress", {})
            emails.append({
                "id": msg.get("id"),
                "subject": msg.get("subject", "(No Subject)"),
                "from_name": from_info.get("name", "Unknown"),
                "from_email": from_info.get("address", "Unknown"),
                "received_at": msg.get("receivedDateTime"),
                "is_read": msg.get("isRead", False),
                "preview": msg.get("bodyPreview", "")[:200],  # First 200 chars
                "body_html": msg.get("body", {}).get("content", ""),
                "has_attachments": msg.get("hasAttachments", False),
                "to_recipients": [r.get("emailAddress", {}).get("address", "") 
                                  for r in msg.get("toRecipients", [])],
                "cc_recipients": [r.get("emailAddress", {}).get("address", "") 
                                  for r in msg.get("ccRecipients", [])],
            })
        
        logger.info(f"Fetched {len(emails)} emails from {folder}")
        return {
            "success": True, 
            "message": f"Retrieved {len(emails)} emails", 
            "emails": emails
        }
        
    except Exception as e:
        error_msg = f"Failed to fetch emails: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg, "emails": []}


def get_email_by_id(email_id: str) -> dict:
    """
    Fetch a specific email by ID with full body content.
    
    Args:
        email_id: The Microsoft Graph email ID
    
    Returns:
        dict with 'success' (bool), 'message' (str), and 'email' (dict)
    """
    credentials = get_email_credentials()
    
    if not all([credentials["tenant_id"], credentials["client_id"], 
                credentials["client_secret"], credentials["sender_email"]]):
        return {"success": False, "message": "Missing email credentials", "email": None}
    
    try:
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        user_email = credentials["sender_email"]
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{email_id}"
        
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            params={
                "$select": "id,subject,from,receivedDateTime,isRead,body,hasAttachments,toRecipients,ccRecipients,attachments"
            },
            timeout=30,
        )
        
        if response.status_code >= 300:
            error_msg = f"Failed to fetch email: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg, "email": None}
        
        msg = response.json()
        from_info = msg.get("from", {}).get("emailAddress", {})
        
        email = {
            "id": msg.get("id"),
            "subject": msg.get("subject", "(No Subject)"),
            "from_name": from_info.get("name", "Unknown"),
            "from_email": from_info.get("address", "Unknown"),
            "received_at": msg.get("receivedDateTime"),
            "is_read": msg.get("isRead", False),
            "body_html": msg.get("body", {}).get("content", ""),
            "body_type": msg.get("body", {}).get("contentType", "html"),
            "has_attachments": msg.get("hasAttachments", False),
            "to_recipients": [r.get("emailAddress", {}).get("address", "") 
                              for r in msg.get("toRecipients", [])],
            "cc_recipients": [r.get("emailAddress", {}).get("address", "") 
                              for r in msg.get("ccRecipients", [])],
        }
        
        logger.info(f"Fetched email: {email['subject']}")
        return {"success": True, "message": "Email retrieved", "email": email}
        
    except Exception as e:
        error_msg = f"Failed to fetch email: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg, "email": None}


def get_email_attachments(email_id: str) -> dict:
    """
    Get attachments for a specific email.
    
    Args:
        email_id: The Microsoft Graph email ID
    
    Returns:
        dict with 'success' (bool), 'message' (str), and 'attachments' (list)
        Each attachment has: id, name, content_type, size
    """
    credentials = get_email_credentials()
    
    if not all([credentials["tenant_id"], credentials["client_id"], 
                credentials["client_secret"], credentials["sender_email"]]):
        return {"success": False, "message": "Missing email credentials", "attachments": []}
    
    try:
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        user_email = credentials["sender_email"]
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{email_id}/attachments"
        
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        
        if response.status_code >= 300:
            error_msg = f"Failed to get attachments: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg, "attachments": []}
        
        data = response.json()
        attachments_data = data.get("value", [])
        
        attachments = []
        for att in attachments_data:
            attachments.append({
                "id": att.get("id"),
                "name": att.get("name", "unknown"),
                "content_type": att.get("contentType", "application/octet-stream"),
                "size": att.get("size", 0),
                "is_inline": att.get("isInline", False),
            })
        
        logger.info(f"Found {len(attachments)} attachments for email {email_id}")
        return {"success": True, "message": f"Found {len(attachments)} attachments", "attachments": attachments}
        
    except Exception as e:
        error_msg = f"Failed to get attachments: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg, "attachments": []}


def download_attachment(email_id: str, attachment_id: str) -> dict:
    """
    Download a specific attachment from an email.
    
    Args:
        email_id: The Microsoft Graph email ID
        attachment_id: The attachment ID
    
    Returns:
        dict with 'success' (bool), 'message' (str), 'content' (bytes), 
        'name' (str), and 'content_type' (str)
    """
    import base64
    
    credentials = get_email_credentials()
    
    if not all([credentials["tenant_id"], credentials["client_id"], 
                credentials["client_secret"], credentials["sender_email"]]):
        return {"success": False, "message": "Missing email credentials", "content": None}
    
    try:
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        user_email = credentials["sender_email"]
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{email_id}/attachments/{attachment_id}"
        
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=60,  # Longer timeout for large files
        )
        
        if response.status_code >= 300:
            error_msg = f"Failed to download attachment: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg, "content": None}
        
        data = response.json()
        
        # File attachments have contentBytes (base64 encoded)
        content_bytes_b64 = data.get("contentBytes")
        if content_bytes_b64:
            content = base64.b64decode(content_bytes_b64)
        else:
            # Item attachments (like embedded emails) don't have contentBytes
            return {"success": False, "message": "Attachment is not a file (may be embedded item)", "content": None}
        
        result = {
            "success": True,
            "message": "Attachment downloaded",
            "content": content,
            "name": data.get("name", "attachment"),
            "content_type": data.get("contentType", "application/octet-stream"),
            "size": data.get("size", len(content)),
        }
        
        logger.info(f"Downloaded attachment: {result['name']} ({result['size']} bytes)")
        return result
        
    except Exception as e:
        error_msg = f"Failed to download attachment: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg, "content": None}


def mark_email_as_read(email_id: str, is_read: bool = True) -> dict:
    """
    Mark an email as read or unread.
    
    Args:
        email_id: The Microsoft Graph email ID
        is_read: True to mark as read, False to mark as unread
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    credentials = get_email_credentials()
    
    if not all([credentials["tenant_id"], credentials["client_id"], 
                credentials["client_secret"], credentials["sender_email"]]):
        return {"success": False, "message": "Missing email credentials"}
    
    try:
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        token = credential.get_token("https://graph.microsoft.com/.default").token
        
        user_email = credentials["sender_email"]
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{email_id}"
        
        response = requests.patch(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"isRead": is_read},
            timeout=30,
        )
        
        if response.status_code >= 300:
            error_msg = f"Failed to update email: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
        
        status = "read" if is_read else "unread"
        logger.info(f"Marked email as {status}")
        return {"success": True, "message": f"Email marked as {status}"}
        
    except Exception as e:
        error_msg = f"Failed to update email: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg}


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

