# Inbound Compliance/Legal/Support Inquiry Processing Checklist

## Doc ID: AGT-CHECK-R4  
## Audience: Tier 2+ Support Agents, Legal Assistants, Autonomous Agent Workflows  
## Last Reviewed: 2025-07-15  
## Automation Compatible: ✅  
## Required for: All high-risk inbound topics

---

### STEP 1: CLASSIFICATION

✅ Classify the inquiry into one or more domains:
- [ ] Data Privacy (GDPR, CCPA, LGPD, PIPEDA)
- [ ] Financial Controls (SOX, SEC, ISO 27001)
- [ ] Ethical or COI Concerns
- [ ] External Regulatory Requests (e.g., FCA, FINRA, ESMA)
- [ ] Internal Support / Ticket-based Issue

Use tag system: `#domain:privacy`, `#domain:sox`, `#domain:support`

---

### STEP 2: IDENTITY & SCOPE VALIDATION

✅ Determine if the sender is authenticated:
- [ ] Validated user credentials via SSO or API token
- [ ] Region-specific compliance (e.g., EEA for GDPR)

If scope unclear, tag: `#scope-review-needed`

---

### STEP 3: DATA ARTIFACTS COLLECTION

✅ Retrieve internal documents:
- [ ] Primary policy reference (vault ID or policy slug)
- [ ] Last compliance audit (PDF or markdown summary)
- [ ] Agent logs linked to inquiry context

✅ Trigger agent tools:
- [ ] `PolicySearchAgent("gdpr")`
- [ ] `FileSummaryAgent("coi_adjudication_log")`

---

### STEP 4: DRAFT RESPONSE STRUCTURE

✅ Response must include:
- [ ] Source reference (policy + audit ID)
- [ ] Disclaimer (match category from library)
- [ ] Escalation notes, if any
- [ ] Full response context saved to: `obs://trace/logs/RESP-ID-xxxx`

---

### STEP 5: AUDIT & ESCALATION LOGGING

✅ Log all completed steps in:
- [ ] `agent_compliance_audit_log.md`
- [ ] If legal ambiguity: forward to `legal.office@corp.net`
- [ ] Attach tags:
  - `#resolved`
  - `#legal-escalation`
  - `#draft-reviewed`

