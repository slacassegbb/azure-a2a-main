# Bank ServiceNow Incident Classification & Analysis Handbook

This document provides a comprehensive set of guidelines, mappings, and reference data for AI agents to analyze, classify, and prioritize bank incident tickets for ServiceNow.  
**Use this file as the authoritative knowledge source for automated or human-assisted ticket creation and management.**

---

## Table of Contents

1. [Incident Categories & Subcategories](#incident-categories--subcategories)
2. [Field Mapping to ServiceNow](#field-mapping-to-servicenow)
3. [Urgency, Impact, and Priority Mapping](#urgency-impact-and-priority-mapping)
4. [Category Keyword Cues & Example Phrases](#category-keyword-cues--example-phrases)
5. [Classification and Analysis Best Practices](#classification-and-analysis-best-practices)
6. [Fallback & Edge Case Handling](#fallback--edge-case-handling)
7. [Appendix: Example Field Mappings](#appendix-example-field-mappings)

---

## Incident Categories & Subcategories

**Assign every incident a primary `category` and, when possible, a more specific `subcategory` using the lists below.**

| **Category**      | **Subcategories**                      | **Definition**                                                                             |
|-------------------|----------------------------------------|--------------------------------------------------------------------------------------------|
| **Fraud**         | Unauthorized Transaction, Phishing, Account Takeover, Card Blocked, Suspicious Communication | Any incident suggesting unauthorized account activity, fraud, or security compromise.       |
| **Technical Issue**| App Login Failure, Website Down, Mobile App Crash, Online Banking Error, Password Reset Failure | Inability to use bank digital services due to technical malfunction.                   |
| **Payment Issue** | Failed Payment, Delayed Transfer, ATM Error, Payment Not Received, Double Charge | Problems with funds transfer, payment processing, or ATM services.                         |
| **Card Issue**    | Lost Card, Stolen Card, Card Not Received, Card Blocked, Damaged Card, Declined Transaction | Problems with physical or virtual cards not working as intended or compromised.            |
| **Account Service**| Address Change, Credit Limit Request, Statement Request, Personal Info Update, Account Closure | Requests for maintenance, documentation, or changes to account.                            |
| **Security**      | Phishing, Compromised Account, Suspicious Login, Security Notification, Credential Reset | Security concerns, credential compromise, social engineering attempts.                     |
| **Inquiry**       | Product Information, Branch Hours, Fee Explanation, General Feedback | General questions, requests for information, or non-urgent feedback.                       |
| **Other**         | Miscellaneous, Out-of-Scope, Feedback  | Anything not covered above.                                                                |

---

## Field Mapping to ServiceNow

| **ServiceNow Field** | **Description/Usage**                                    | **Typical Values/Examples**                      |
|----------------------|----------------------------------------------------------|--------------------------------------------------|
| `short_description`  | Short summary of the incident                            | "Card lost in transit"                           |
| `description`        | Detailed explanation and relevant context                | "Customer lost card during travel in Rome."      |
| `category`           | Main incident category                                   | "Card Issue"                                     |
| `subcategory`        | More specific incident type                              | "Lost Card"                                      |
| `urgency`            | Customer/business urgency: 1 (High), 2 (Medium), 3 (Low)| 1 = "Funds blocked", 2 = "Delayed transfer"      |
| `impact`             | Severity of effect: 1 (High), 2 (Medium), 3 (Low)       | 1 = "Cannot access account", 3 = "Info request"  |
| `priority`           | System-computed: 1 (Critical) to 5 (Planning)           | Calculated from urgency/impact                   |

---

## Urgency, Impact, and Priority Mapping

**Urgency**
- 1 (High): Loss of funds, account/card blocked, confirmed fraud, or security breach
- 2 (Medium): Service disruption or delay, but not a loss of funds/security
- 3 (Low): Routine, informational, or minor inconvenience

**Impact**
- 1 (High): Customer is blocked from core banking functions, major loss or risk
- 2 (Medium): Partial disruption, temporary limitation
- 3 (Low): No major impact, general request

**Priority Matrix (ServiceNow Standard)**

| Urgency | Impact | Priority | Priority Label  |
|---------|--------|----------|----------------|
| 1       | 1      | 1        | Critical       |
| 1       | 2      | 2        | High           |
| 2       | 2      | 3        | Moderate       |
| 2       | 3      | 4        | Low            |
| 3       | 3      | 5        | Planning       |

**Default Category-Based Mapping**

| Category        | Default Urgency | Default Impact | Default Priority |
|-----------------|-----------------|---------------|-----------------|
| Fraud           | 1 (High)        | 1 (High)      | 1 (Critical)    |
| Security        | 1               | 1             | 1               |
| Card Issue      | 1               | 1             | 1               |
| Technical Issue | 2 (Medium)      | 2 (Medium)    | 3 (Moderate)    |
| Payment Issue   | 2               | 2             | 3               |
| Account Service | 3 (Low)         | 3 (Low)       | 5 (Planning)    |
| Inquiry         | 3               | 3             | 5               |
| Other           | 2               | 3             | 4 (Low)         |

> **Override defaults if the customer clearly states an urgency or business impact.**

---

## Category Keyword Cues & Example Phrases

### Fraud
- **Keywords:** unauthorized, fraud, unknown charge, not me, suspicious, scam, phishing, blocked card
- **Examples:**  
  - "I did not make this charge in Milan."
  - "My account has been compromised."
  - "Received an email asking for my banking password."

### Technical Issue
- **Keywords:** app, login, error, website, cannot access, crash, reset password
- **Examples:**  
  - "I can't log into my bank app."
  - "Online banking page keeps crashing."
  - "Password reset not working."

### Payment Issue
- **Keywords:** payment failed, transfer delayed, not received, ATM, charged twice, deposit
- **Examples:**  
  - "ATM deducted money but did not dispense cash."
  - "My transfer hasn't arrived."
  - "Was charged twice for my loan payment."

### Card Issue
- **Keywords:** lost card, stolen, card not received, card blocked, declined, damaged, not working
- **Examples:**  
  - "Lost my card while traveling."
  - "My card was declined at checkout."
  - "I have not received my new card yet."

### Account Service
- **Keywords:** address change, update info, credit limit, statement, close account, reopen
- **Examples:**  
  - "Need to update my address."
  - "Request to increase my credit limit."
  - "Want to close my account."

### Security
- **Keywords:** phishing, compromised, suspicious login, security alert, credential reset
- **Examples:**  
  - "Received a phishing email."
  - "There was a login from an unknown device."
  - "My password was reset without my request."

### Inquiry
- **Keywords:** information, branch hours, product details, fees, feedback, how to
- **Examples:**  
  - "What are your branch hours?"
  - "What is the interest rate for savings accounts?"
  - "I want to give feedback about your service."

### Other
- **Keywords:** feedback, complaint, out of scope, not listed, miscellaneous
- **Examples:**  
  - "I'd like to make a complaint."
  - "My issue does not fit the categories listed."

---

## Classification and Analysis Best Practices

1. **Read both `short_description` and full `description` before classifying.**
2. **If fraud, security, or loss of access to funds is mentioned,** default to highest urgency/impact/priority.
3. **For technical/service problems,** check if customer is fully blocked (higher urgency) or just inconvenienced (medium/low).
4. **Use keywords as signals, but always consider context.**
5. **If a ticket clearly mentions urgency or business impact, override defaults.**
6. **For ambiguous/multiple matches, pick the category with the highest risk/impact.**
7. **If the category is unclear, assign "Other" and flag for review.**

---

## Fallback & Edge Case Handling

- If the ticket matches more than one category, **choose the one with highest urgency and impact**.
- If in doubt, assign "Other" and include a note in the description or work_notes for human triage.
- For language variations, use translation/localization to identify keywords if possible.
- Escalate tickets that could be potential compliance/regulatory issues, even if not explicitly mentioned.

---

## Appendix: Example Field Mappings

**Example 1:**
- `short_description`: "Fraudulent charge in Milan"
- `description`: "Customer reports an unknown $200 charge in Milan while traveling in Rome."
- `category`: "Fraud"
- `subcategory`: "Unauthorized Transaction"
- `urgency`: 1
- `impact`: 1
- `priority`: 1

**Example 2:**
- `short_description`: "App login failure"
- `description`: "User cannot log in to the bank mobile app. Error: credentials invalid."
- `category`: "Technical Issue"
- `subcategory`: "App Login Failure"
- `urgency`: 2
- `impact`: 2
- `priority`: 3

**Example 3:**
- `short_description`: "Request for branch hours"
- `description`: "Customer wants to know branch hours for the Montreal location."
- `category`: "Inquiry"
- `subcategory`: "Branch Hours"
- `urgency`: 3
- `impact`: 3
- `priority`: 5

---

**End of Bank ServiceNow Incident Classification & Analysis Handbook**

---

