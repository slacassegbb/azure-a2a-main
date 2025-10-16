# General Data Protection Regulation (GDPR) — Internal Reference Summary

## Policy ID: GDPR-COMP-V5.2
## Jurisdiction: EU + UK GDPR
## Controlled By: Data Protection Office (DPO)
## Reviewed: Quarterly (latest: 2025-06-30)
## Enforcement Tier: Critical (P1)

---

### 1. Lawful Basis for Data Processing

| Legal Basis      | Description                                                                 |
|------------------|-----------------------------------------------------------------------------|
| Consent          | Explicit user agreement (Article 6(1)(a))                                   |
| Contract         | Processing necessary for contract fulfillment (Article 6(1)(b))             |
| Legal obligation | Required by law (Article 6(1)(c))                                           |
| Vital interest   | Protection of life (Article 6(1)(d))                                        |
| Public task      | Tasks in public interest or official authority (Article 6(1)(e))            |
| Legitimate interest | Balance test must be documented and filed (Article 6(1)(f))              |

Documentation of lawful basis must be retrievable via: `vault://privacy/basis-audit-log.md`

---

### 2. Data Subject Rights & Obligations

| Right                          | Description                                                             | Agent Required Action         |
|--------------------------------|-------------------------------------------------------------------------|-------------------------------|
| Right to access (Art. 15)      | Provide copy of data, processing purpose, and third-party disclosures   | Generate PDF summary using `DSAR-AI` agent |
| Right to rectification (Art. 16)| Correct inaccurate or incomplete data                                  | Submit internal change form `DPO-FIX-14B`  |
| Right to erasure (Art. 17)     | Delete data when no longer lawful                                       | Trigger policy engine with `delete:consentID` |
| Right to restrict processing   | Suspend processing on request                                           | Flag `DPO-HOLD` in system metadata |

---

### 3. Cross-Border Transfer Policy

- Transfers outside EEA require:
  - Adequacy decision by EU Commission
  - SCCs (Standard Contractual Clauses) signed and filed
  - Records logged in `transfer-register.md`
  - Data classification: `Sensitive`, `Standard`, `Public`

---

### 4. Incident Management

All GDPR violations must:
- Be reported within 24 hours to `privacy.office@corp.net`
- Be logged under `databreach_tracker.md`
- Include:
  - Incident ID (auto-generated)
  - Data categories affected
  - Recovery action

---

### 5. Agent Enforcement Behavior

Agents must:
- Reject requests without verified identity (flag `IDENTITY-UNVERIFIED`)
- Check policy cache freshness (< 30 days)
- Route edge cases to Legal Advisor Agent
