# CUST005 - Complete Test Scenario

## Customer Information
- **Customer ID**: CUST005
- **Name**: Jennifer Martinez
- **Date of Birth**: September 12, 1988 (1988-09-12)
- **Postal Code**: M2N5W3
- **Address**: 742 Yonge Street, North York, ON M2N5W3
- **Phone**: 416-555-0105
- **Email**: jennifer.martinez@email.com
- **Account Status**: Active
- **Region**: Toronto North

---

## Expected Agent Flow Results

### 1️⃣ **Authentication Agent**
**Status**: ✅ PASS
- Customer exists in database
- Identity verified with name, DOB, postal code
- Returns customer_id: CUST005

---

### 2️⃣ **Outage Check Agent**
**Status**: ✅ NO OUTAGE
- No local outages at customer address
- No regional outages in Toronto North
- `has_local_outage`: false
- `has_regional_outage`: false

---

### 3️⃣ **Modem Check Agent**
**Status**: ⚠️ CRITICAL ISSUE - Blinking Yellow LED

**Modem Information**:
- **Modem ID**: MDM-005-7Q2W
- **Model**: Contoso Ignite Gateway XB7
- **Status**: Booting (continuously rebooting)
- **LED Status**: 🟡 **Blinking Yellow**
- **Uptime**: 0 hours (just rebooted)
- **Last Reboot**: 2025-11-04 at 10:30 AM

**LED Analysis**:
- **Meaning**: "Modem is turning on"
- **Status**: Booting
- **Action**: "Wait for modem to fully boot up (3-5 minutes)"

**Technical Details**:
- Signal Strength:
  - Downstream Power: -6 dBmV
  - Upstream Power: 42 dBmV
  - SNR: 34 dB
- Backend Status: ✅ Provisioned, configuration valid, firmware up to date
- **Connection Quality**: Poor
- **Notes**: Modem continuously rebooting, possible hardware or signal issue

**Agent Diagnosis**: Modem is stuck in boot loop with blinking yellow LED - backend configuration is fine but modem hardware may be failing.

---

### 4️⃣ **Internet Plan Agent**
**Status**: ✅ ACTIVE - Billing Current

**Plan Information**:
- **Plan ID**: PLAN-IGNITE-500
- **Plan Name**: Contoso Ignite 500
- **Speed**: 500 Mbps download / 20 Mbps upload
- **Data Limit**: Unlimited
- **Monthly Cost**: $94.99
- **Contract**: 2-year contract (Started: March 20, 2024 → Ends: March 20, 2026)

**Billing Status**:
- ✅ Last 3 bills paid on time
- ✅ Current balance: $0.00
- Last payment: October 30, 2025 ($94.99)
- Payment history: All paid
  - 2025-10-30: $94.99 ✅
  - 2025-09-30: $94.99 ✅
  - 2025-08-30: $94.99 ✅

**Data Usage**:
- Current billing cycle: Nov 1-30, 2025
- Usage: 423.8 GB (unlimited plan - no overage concerns)

**Access Status**: ✅ Active - Customer in good standing

---

### 5️⃣ **Network Performance Agent**
**Status**: 🚨 CRITICAL - Complete Network Failure

**Network Information**:
- **Network Name**: Martinez_Home_5G
- **Modem IP**: 192.168.1.1
- **Modem Status**: Unstable
- **Total Devices**: 8
- **Active Devices**: 0 (all offline)

**Connected Devices (All Offline)**:
1. Jennifer's Laptop - 192.168.1.101 - OFFLINE
2. Jennifer's iPhone - 192.168.1.102 - OFFLINE
3. Smart TV - 192.168.1.103 - OFFLINE
4. Work Laptop - 192.168.1.104 - OFFLINE
5. Smart Thermostat - 192.168.1.105 - OFFLINE
6. Ring Doorbell - 192.168.1.106 - OFFLINE
7. Smart Speaker - 192.168.1.107 - OFFLINE
8. Tablet - 192.168.1.108 - OFFLINE

**Ping Test Results**:
- **Modem Ping**: 
  - Target: 192.168.1.1
  - Packets Sent: 10
  - Packets Received: 0
  - **Packet Loss: 100%** 🚨
  - Status: **CRITICAL**

**Network Performance**:
- **Overall Status**: CRITICAL
- **Connectivity Issues**: YES
- **Issue Description**: Complete network failure - modem not responding to pings, all devices offline
- **Recommended Action**: Modem hardware issue suspected - requires technician visit for replacement

**Network Reset Attempt**: Would fail - modem not responding to any commands

---

### 6️⃣ **Technical Dispatch Agent**
**Status**: 🔧 SCHEDULE TECHNICIAN

**Decision Factors**:
- ✅ No outages (not an external issue)
- 🟡 Modem showing blinking yellow LED (boot loop)
- 🚨 100% packet loss (complete network failure)
- ✅ Billing is current (not a billing issue)
- ✅ Plan is active (not a service suspension)
- 🔧 Backend configuration is fine
- 🔧 Hardware issue suspected

**Final Diagnosis**: 
Modem hardware failure causing continuous reboot loop. Device cannot establish network connectivity despite proper backend provisioning. This requires on-site technician visit for modem replacement.

**Recommended Action**: 
Schedule technician appointment for modem replacement. Customer cannot work from home and needs urgent service.

---

## Test Script for UX

**Customer Says**: "Hi, my internet isn't working at all. None of my devices can connect."

**Expected Flow**:

1. **Contoso Concierge** → Calls Authentication Agent
   - Returns: Jennifer Martinez verified (CUST005)

2. **Contoso Concierge** → Calls Outage Check Agent
   - Returns: No outages detected in your area

3. **Contoso Concierge** → Requests modem LED video
   - Customer uploads video showing blinking yellow light

4. **Contoso Concierge** → Calls Modem Check Agent
   - Returns: Modem stuck in boot loop, blinking yellow LED, 0% uptime

5. **Contoso Concierge** → Calls Internet Plan Agent
   - Returns: Plan active, billing current, no data issues

6. **Contoso Concierge** → Calls Network Performance Agent
   - Returns: Critical failure, 100% packet loss, all devices offline

7. **Contoso Concierge** → Calls Technical Dispatch Agent
   - Returns: Schedule technician for modem replacement

**Final Response to Customer**:
"Jennifer, I've completed a full diagnostic check. There are no outages in your area, and your account is in good standing with your Ignite 500 plan. However, your modem appears to be experiencing a hardware failure - it's stuck in a continuous reboot cycle (blinking yellow LED) and cannot establish any network connectivity. I've scheduled a technician visit to replace your modem. Would you like the earliest available appointment?"

---

## Human Escalation Test

**Customer Says**: "Can I get service more quickly? I work from home and need internet urgently."

**Expected Flow**:
- **Contoso Concierge** → Calls Technical Dispatch Agent with escalation request
- **Technical Dispatch Agent** → Outputs "HUMAN_ESCALATION_REQUIRED"
- **HITL UI** → Shows pending escalation with full diagnostic summary
- **Human Expert** → Reviews case and responds via Gradio UI
- **Response passed back** → "I've expedited your technician appointment to today at 2PM. I'm also sending you a temporary mobile hotspot device via same-day courier to help you work until the technician arrives."

---

## Summary

**CUST005 (Jennifer Martinez)** is a perfect test case that flows through all 6 agents:
- ✅ Real customer with valid authentication data
- ✅ No outages (tests outage check returning negative)
- 🟡 Modem with blinking yellow LED (boot loop issue)
- 🚨 Network completely down (100% packet loss)
- ✅ Billing current and plan active
- 🔧 Requires technician dispatch (modem hardware replacement)
- 🆘 Can escalate to human for urgent service

This scenario demonstrates the complete diagnostic workflow and leads to a technician appointment being scheduled.
