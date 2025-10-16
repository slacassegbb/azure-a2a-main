VPN Troubleshooting Guidelines & FAQ
Version: 1.0 • Scope: Tier 1–Tier 2 support • Audience: Helpdesk & NOC

0) Quick Triage (60–90s)
Classify symptom: Won’t connect / Slow / Drops / Specific app fails / Can’t reach internal site

Environment: OS (Win/macOS/iOS/Android/Linux), network (home/public/cellular), VPN client name & version.

Auth path: SSO/MFA? Certs? Local creds?

Impact: Single user vs many; started when? any changes?

Action: Pick the matching runbook below; gather logs (see §6).

1) Requirements & Known Good Baseline
Account: Active, not locked; correct group/policy assigned.

Client: Supported version (n-1). Auto-update enabled.

Network:

DNS resolves the VPN gateway/FQDN.

Open ports commonly used by IPsec/IKE/OpenVPN/WireGuard/SSTP (per your stack).

No captive portal; stable latency (<100 ms) and jitter.

Device posture (if enforced): Disk encryption, AV/EDR healthy, firewall on, OS patches current.

MFA: Push/SMS/TOTP reachable and approved within timeout.

2) Standard Runbooks
2.1 Won’t Connect
Typical signals: “Connecting…” hang, auth error, timeouts.
Checklist (Tier 1)

Confirm username realm/UPN, password freshness; test SSO to any corporate SaaS.

MFA: ask user to open authenticator first; retry.

Network:

Switch network (phone hotspot vs Wi-Fi).

Power-cycle home router; disable VPN within VPN/“double VPN” extensions.

Client:

Quit & relaunch; reboot device.

Remove stale profile; re-import config/profile.

Clear DNS cache; flush client state (see §5).
Tier 2

Inspect auth logs for user; verify policy, group, licensing.

Check gateway health & capacity; test from a known-good test box.

Temporarily bypass posture check (if policy allows) to isolate.

2.2 Slow Throughput / High Latency
Typical signals: <5 Mbps, stutter on calls, long page loads.
Checklist (Tier 1)

Compare Speedtest off-VPN vs on-VPN.

Ensure split tunneling configured as expected.

Switch gateway/region.

Prefer wired over Wi-Fi; avoid 2.4 GHz; close heavy downloads.
Tier 2

Check gateway load, packet drops, SNMP/flow; review QoS.

MTU test & adjust (see §5).

Validate no security device is TLS/UDP inspecting VPN traffic.

2.3 Frequent Disconnects / Drops
Typical signals: Drops every 5–15 min, re-auth loops.
Checklist (Tier 1)

Power saving: disable NIC power management (Win), prevent sleep.

Roaming/IP change: user on mobile hotspot? advise stable network.

Time sync: ensure system clock is accurate (SSO/MFA sensitive).
Tier 2

Inspect idle timeout / DPD/keepalive; adjust grace and retry timers.

Review DHCP lease/renew events; Wi-Fi roaming aggressiveness.

2.4 Can Connect but Can’t Reach Internal Apps
Typical signals: Some hosts reachable; others not; names fail.
Checklist (Tier 1)

DNS: can ping by IP? if yes but name fails → flush DNS; check suffix search list.

Routes: confirm internal subnets appear in route table; verify split vs full tunnel.

App: confirm URL/port; try HTTP vs HTTPS; bypass proxy.
Tier 2

Verify push routes and access lists for user group.

Check hairpin/NAT rules; validate firewall policy on app side.

2.5 MFA/SSO Issues
Resync TOTP time; ensure push notifications allowed.

Clear browser SSO cookies; try private window.

Reset device binding if using number matching / device enrollment.

3) OS-Specific Quick Commands
Replace vpncli with your client binary; adjust as needed.

Windows
Status: Get-VpnConnection

Flush DNS: ipconfig /flushdns

Reset Winsock: netsh winsock reset (reboot after)

MTU test: ping <gateway> -f -l 1472 (reduce till no fragmentation)

macOS
Status: scutil --nc list / scutil --nc status "<profile>"

DNS cache: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

Routes: netstat -rn

MTU: networksetup -getMTU <service>

Linux
Status: nmcli con show --active

Routes: ip route

DNS: resolvectl status or cat /etc/resolv.conf

MTU: ip link set dev <iface> mtu 1400 (test)

iOS/Android
Toggle Airplane mode; forget/re-add Wi-Fi; reinstall profile/app; ensure battery optimization exclusions for VPN app.

4) Error Code Mapping (Template)
Error Code/Msg	Meaning	Likely Cause	First Fix
AUTH_FAILED / “Creds invalid”	Identity rejected	Expired pwd / wrong realm / locked	Reset pwd; verify UPN; unlock account
TIMEOUT / “Gateway unreachable”	No response from server	Firewall/NAT, DNS, ISP block	Try TCP fallback; switch network; check ports
CERT_VALIDATION_FAILED	TLS/cert trust failed	Expired/intermediate CA missing	Update trust store; reinstall client/cert
POSTURE_NON_COMPLIANT	Device check failed	AV off, disk not encrypted	Fix posture; re-evaluate
MFA_DENIED / EXPIRED	Second factor not approved	No push/TOTP out-of-sync	Approve within window; resync TOTP

Adapt with your product-specific codes.

5) Quick Fix Snippets
Flush client state (generic)

arduino
Copy
Edit
vpncli disconnect
vpncli clear-cache
vpncli restart
DNS reset sequence (Windows)

bash
Copy
Edit
ipconfig /flushdns
ipconfig /registerdns
net stop dnscache & net start dnscache
MTU Troubleshooting (generic)

Find largest unfragmented ping (Win example):

php-template
Copy
Edit
ping <internal_host> -f -l 1472
When it works, set MTU = payload + 28 (IP/ICMP overhead).

6) Logs & What to Capture
Platform	Client Logs Path (example)	System Logs
Windows	%ProgramData%\Vendor\VPN\logs\	Event Viewer → Applications & Services → VPN
macOS	~/Library/Logs/VPNClient/	Console.app (filter by client/gateway)
Linux	/var/log/<vpnclient>/	journalctl -u <vpnservice>
iOS/Andr.	In-app export	Device syslog (if available)

Always collect: timestamp, gateway, username (or user ID), client version, network (ISP/SSID), error text, repro steps.

7) Decision Trees (Condensed)
A. Auth Fails

Can user log into any corporate SaaS?

No → credentials/MFA → reset/fix → retry.

Yes → client/gateway → try alternate gateway → check policies/logs.

B. Name Resolution Fails

Ping by IP works?

Yes → DNS path (suffixes, split-DNS, resolver).

No → routing/NAT/firewall to subnet.

C. Drops

Only on Wi-Fi? → test wired → check power save & roaming.

On all networks → DPD/keepalive/timeout → adjust policy.

8) Escalation Matrix
Tier 1 → Tier 2 when:

Repeated auth/timeouts after baseline checks.

Multi-user/regional impact.

Requires route/ACL/QoS/policy edits or gateway change.

Tier 2 → NOC/Infra when:

Gateway CPU/conn limit saturation, ISP outage, cert rollover, CA issues.

Widespread DNS failures or SSO IdP incident.

Include: ticket #, users affected, timestamps (with TZ), gateways, logs bundle, traceroute to gateway, Speedtest screenshots.

9) FAQs (Agent-Facing)
Q1: User says “VPN breaks my internet.”
A: Likely full-tunnel policy or DNS hijack by captive portal. Confirm split/full, re-auth after bypassing captive portal.

Q2: Which ports/protocols do we need?
A: Document your stack explicitly (e.g., IKEv2: UDP 500/4500; OpenVPN: UDP/TCP 1194; WireGuard: UDP 51820; SSTP: TCP 443). Ask user’s network admin to allow outbound and NAT.

Q3: Do we support double VPN / other VPN apps?
A: Not supported. Ask user to disable/quit other VPNs and browser VPN extensions.

Q4: Why does SSO work but VPN auth fails?
A: Different app scopes/conditional access, or device posture requirement. Check policy assignment & posture results.

Q5: User can reach some internal apps but not others.
A: Missing routes/ACLs or app firewall. Compare working vs failing subnets; confirm DNS split.

Q6: When do we reinstall the client?
A: After cache reset and profile re-import fail; ensure you save tokens/profiles or provide new package.

Q7: Can the user work without VPN?
A: If app supports ZTNA/Reverse Proxy, advise direct access path; otherwise VPN is required.

10) Call Handling Script (Neutral)
Open: “Let’s get you working. I’ll run quick checks and we’ll fix the fastest blocker first.”

Expectation set: “If the first pass doesn’t land, I’ll escalate with your logs so you won’t repeat steps.”

Close: Summarize fix and prevention (e.g., “Keep authenticator open before connecting; if speed dips, switch to Gateway-2”).

11) Maintenance & Hygiene (Ops)
Rotate and monitor gateway certs; track client version adoption.

Capacity planning (concurrent sessions, throughput, CPU).

Synthetic canaries: periodic auth + small file transfer from key geos.

Post-incident reviews: capture MTTR, top error codes, fix playbooks.

12) Appendix: Replace-Me Variables (for your environment)
Gateway FQDNs: vpn01.company.com, vpn02.company.com

Ports/Protocols: (list exact set for your product)

Client Name & Version policy: (n-1 supported, auto-update cadence)

Log export how-to: (screenshots/steps link)

Escalation contacts: NOC on-call, IdP owner, Network firewall on-call