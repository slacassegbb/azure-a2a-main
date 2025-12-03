# Email Agent Guide

## Overview

The Email Agent can send emails on your behalf using Microsoft Graph API. It integrates with your Microsoft 365 environment to send professional emails.

## Capabilities

### 1. Send Simple Emails
Send a basic email to any recipient with a subject and body.

**Example:**
```
Send an email to john@example.com saying the meeting is at 3pm tomorrow
```

### 2. Professional Email Composition
The agent will compose professional emails with:
- Proper greetings (Hi, Hello, Dear)
- Well-structured body content
- Professional sign-offs (Best regards, Thanks, etc.)
- HTML formatting for better readability

### 3. CC Recipients
Send emails to multiple people by adding CC recipients.

**Example:**
```
Send an email to john@example.com and CC mary@example.com about the project update
```

### 4. HTML Formatting
Emails are sent with HTML formatting for:
- Bold and italic text
- Bullet points and numbered lists
- Headers and sections
- Links

## Best Practices

### Subject Lines
- Keep them concise and descriptive
- Include key information upfront
- Avoid ALL CAPS or excessive punctuation

### Email Body
- Start with a greeting
- State the purpose clearly
- Use paragraphs for readability
- Include a call to action if needed
- End with a professional closing

### Timing
- The agent will ask for confirmation before sending
- Review the preview to ensure accuracy
- Verify recipient email addresses

## Common Use Cases

1. **Meeting Coordination**
   - Scheduling meetings
   - Sending reminders
   - Rescheduling notifications

2. **Project Updates**
   - Status updates
   - Milestone notifications
   - Deadline reminders

3. **Professional Communication**
   - Thank you notes
   - Follow-up messages
   - Introduction emails

4. **Client Communication**
   - Proposals and quotes
   - Project updates
   - General correspondence

## Troubleshooting

### Email Not Sending
- Verify the recipient email address is valid
- Check that Microsoft Graph credentials are configured
- Ensure the sender email has permission to send

### Formatting Issues
- The agent uses HTML formatting
- Plain text fallback is available
- Some email clients may render HTML differently

## Security

- Emails are sent through Microsoft Graph API
- Sender authentication uses Azure AD
- All communications are encrypted in transit


