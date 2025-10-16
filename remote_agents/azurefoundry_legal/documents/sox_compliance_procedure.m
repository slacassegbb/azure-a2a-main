# SOX ITGC Compliance: Procedure Reference Guide

## Policy ID: SOX-ITGC-V4.1
## Governs: Financial Systems, Logs, Access Control, Change Management
## Maintained by: Internal Audit + Enterprise Risk Management (ERM)
## SOX Scope Map: `vault://sox/system_scope_2025.md`

---

### 1. Critical Controls Summary

| Control Area         | Description                                                                   | Enforcement Method        |
|----------------------|-------------------------------------------------------------------------------|---------------------------|
| User Access Review   | Quarterly validation of RBAC by System Owner + Security Team                  | Signed attestations stored in `access-audit-trail.md` |
| Change Management    | All production changes must follow CAB review and rollback documentation      | Changes via ITSM only     |
| Logging & Retention  | System logs must be immutable and retained for minimum of 7 years             | Enforced via SIEM ruleset |

---

### 2. Agent Responsibilities

Agents generating responses involving financial data must:
- Verify whether system is in SOX scope
- Cite last successful audit (`Audit-Ref-ID: Q2-2025-KPMG`)
- Include disclaimer from `legal_disclaimer_library.md` category: *Financial Records*

Sample snippet:
> “This information pertains to a SOX-audited system (Scope ID: SOX-FIN-SYS-2025). All access and operations are governed under Section 404 of the Sarbanes-Oxley Act. Please note this is not a certification of compliance.”

---

### 3. Control Evidence Index

| Artifact                        | Source                      | Access                         |
|--------------------------------|-----------------------------|--------------------------------|
| RBAC Review Logs               | `logs://sox/rbac-Q2-2025.csv`| Read-only                      |
| Audit Control Narratives       | `vault://sox/narratives.md` | Internal Legal + Audit Team   |
| SOX Audit Certs (external)     | `audit://kpmg/q2_2025.pdf`  | Legal only (encrypted)        |

---

### 4. Violations & Reporting

All SOX violations must be filed using `SOX-REPORT-FORM-9A` and tagged with:
- `#sox-critical`
- `#section302`
- `#audit-disclosure`

Remediation tracking must be linked to: `risk-register.md`
