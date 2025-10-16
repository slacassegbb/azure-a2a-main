# Regulatory Communications & Risk-Aware Drafting Standards

## Document ID: REGCOM-STD-V7
## Maintained by: Risk & Regulatory Affairs Office (RRAO)
## Last Revised: 2025-07-12
## Applies to: All AI agents, Legal Operations, Compliance, Tier 2+ Support Staff

---

### 1. Purpose

To define the approved structure, tone, and workflows for generating external-facing communications that may contain legal, regulatory, or risk-sensitive content. This ensures regulatory alignment, mitigates legal exposure, and standardizes cross-functional authoring practices.

---

### 2. Scope

This document applies to all human-authored and AI-generated outputs that:
- Reference internal policies or regulatory frameworks
- Involve financial, legal, or customer-sensitive issues
- Include disclaimers or legal citations
- Are retained in the audit trail under SOX or GDPR provisions

---

### 3. Drafting Rules

#### 3.1 Tone & Structure

| Element         | Guideline                                                       |
|----------------|------------------------------------------------------------------|
| Tone            | Formal, neutral, unambiguous                                    |
| Formatting      | Use Markdown for digital responses; plaintext for legacy systems|
| Dates           | Always use ISO 8601 (`YYYY-MM-DD`) format                       |
| Voice           | Passive voice discouraged unless citing regulation              |
| Citations       | Use full legal reference: “per Article 6(1)(a) of the GDPR”     |

#### 3.2 Prohibited Language
Do not use:
- “We believe,” “We assume,” or “We expect” without qualifiers
- Informal phrasing (e.g., “just to be sure”)
- Legal interpretations unless inserted via authorized Legal Agent

---

### 4. Required Elements

Each response must include:
- Timestamp and system identifier
- Internal response reference ID
- Section header indicating source (e.g., GDPR Policy v5)
- Associated disclaimer (see `legal_disclaimer_library.md`)
- Link to primary policy document in vault (e.g., `vault://compliance/gdpr_v5.md`)

---

### 5. Escalation Criteria

Escalate to Legal Counsel if:
- Unclear jurisdiction
- Financial or criminal liability involved
- Cross-border data handling without consent
- Customer disputes regulatory basis

Use escalation tag: `RRAO-ESCALATE-L1`

---

### 6. Auditing & Logging

All agent responses in this domain must:
- Be stored in compliance data lake for 7 years
- Include log tags: `#regulatory`, `#legal`, `#tier2`, `#agent-id`
- Link to full draft trace in observability UI (e.g., `obs://agent-logs/txn-44b2a`)

