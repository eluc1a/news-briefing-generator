# themorningfox.com / feed — DDoS Protection Mitigations — Handoff

**Branch:** `dev` (HEAD `518d4d5`)
**Date:** 2026-06-18
**Scope:** Infrastructure (nginx, host firewall, DNS/Cloudflare on `fox`, LAN `192.168.0.89`) — **not** code in this repo.
**Related:** `~/security-audit-2026-06-16.md` (host security audit; nginx hardening + host firewall already flagged there as open items)

---

## TL;DR

A review of DDoS exposure for the public sites (`themorningfox.com` broadsheet + `feed.themorningfox.com/ai-digest` Slack digest) found **no meaningful DDoS protection**. Both domains resolve directly to the home origin IP `68.84.4.134` (via TP-Link dynamic DNS `elucia.tplinkdns.com`) — **neither is proxied through Cloudflare**, so the origin IP is publicly exposed and there is no edge scrubbing. nginx has **no rate limiting**. fail2ban *is* active (`nginx-env` + `sshd` jails, already banning scanners) but that is reactive single-IP scanner/brute-force mitigation, **not** distributed-volumetric DDoS protection.

The pages themselves are the *least* attractive target: they are flat static files (HTML/JSON/XML) served straight by nginx with no DB query, no LLM call, no Python on the request path — so an application-layer flood barely loads the box. **The real exposure is the residential uplink**: a volumetric flood saturates the home connection upstream of nginx/fail2ban (which can't help once the pipe is full) and would take down the whole connection, not just the site.

No changes were made this session — this is a write-up of findings + a prioritized plan to implement later. Decision pending from the user: whether to go the Cloudflare-proxy route (touches DNS + TLS + origin firewall together) or stick to local nginx/firewall hardening only.

---

## What was done this session

Investigation only — read-only checks against the live `fox` host. Verbatim findings:

- **DNS / Cloudflare proxy status** (`dig +short`): both `themorningfox.com` and `feed.themorningfox.com` → `68.84.4.134` (home IP; `feed.` is a CNAME to `elucia.tplinkdns.com`). **Not** Cloudflare IP ranges (104.x / 172.67.x), i.e. grey-cloud / DNS-only → origin exposed, no edge DDoS protection.
- **nginx rate limiting**: `grep -rn "limit_req\|limit_conn" /etc/nginx/` → **NONE**. `/etc/nginx/nginx.conf` is world-readable (`.rw-r--r-- root`).
- **fail2ban**: `active`; 2 jails — `nginx-env`, `sshd`. Already banning scanner IPs (e.g. `137.184.26.172`, `185.224.128.52` appear as iptables DROPs).
- **Host firewall**: no `ufw` installed; `iptables` INPUT policy = `ACCEPT`. INPUT chain contains only `piavpn.INPUT`, the fail2ban `f2b-nginx-env` chain (tcp dpt:80), and per-IP DROPs from fail2ban. **No default-deny.**
- **Connection type**: residential broadband behind TP-Link dynamic DNS — limited upstream bandwidth, the key DDoS chokepoint.

Context note: confirms + extends the `[[fox-security-posture]]` memory, which said internet surface is 80/443/51820 and flagged "no host firewall / nginx hardening" as remaining. New detail: fail2ban *is* providing targeted iptables drops (so it's not "nothing"), but there is no rate limiting and no default-deny firewall, and **both** prod domains are unproxied (memory had only described `feed.` as a grey-cloud CNAME).

---

## What is NOT done (the actual work, prioritized)

1. **nginx rate limiting (lowest risk, do first).** Add a `limit_req_zone` (e.g. keyed on `$binary_remote_addr`) in the `http {}` block and `limit_req` in the relevant `server`/`location` blocks for the static vhosts. No DNS/cert changes, purely additive. Defense-in-depth against app-layer / single-source floods. Start: locate the vhost files (`/etc/nginx/sites-enabled/` or `conf.d/`), pick a sane rate (static files → generous, e.g. 20r/s with burst), `nginx -t` then reload.
2. **Default-deny host firewall.** Currently INPUT policy is ACCEPT. Lock to 80/443/51820 (+ LAN/SSH from `192.168.0.0/24`) with a default DROP. Coordinate with the existing `piavpn.INPUT` chain and fail2ban's chains so nothing is clobbered. Already an open item in `~/security-audit-2026-06-16.md`.
3. **Cloudflare proxy migration (highest leverage, biggest blast radius — needs its own plan).** Flip both domains to orange-cloud (proxied). Free tier gives unmetered L3/L4 volumetric DDoS protection + hides the origin IP; static site can be fully edge-cached. **Must be done as a unit with two prerequisites or it's bypassable / breaks:**
   - **(a)** After proxying, lock the origin firewall so 80/443 accept **only** Cloudflare IP ranges — otherwise attackers hit `68.84.4.134` directly and bypass the edge.
   - **(b)** TLS changes: current setup is a webroot Let's Encrypt cert (per `[[slack-digest-rss-delivery]]` / domain-migration handoff). With CF proxy, switch to CF edge cert + a CF Origin Certificate on nginx. Verify `feed.themorningfox.com` cert + the LE renewal path (webroot is `/var/www/html`, port 80 = Apache default vhost; 443 = nginx — see `2026-06-15-feed-domain-migration-handoff.md`).
   - Dynamic-DNS caveat: origin IP changes when the home IP rotates; CF proxy must keep the origin record (grey, behind the orange one) pointed at the current IP via the TP-Link DDNS, or use CF API DDNS updates.

---

## Decision pending (user)

> User asked only to "write up a handoff … so we can do it later." No go-ahead to implement anything yet.

Choose the path before implementing:
- **Minimal:** items 1 + 2 only (nginx rate limit + host firewall). Keeps DNS/TLS untouched. Does **not** protect against volumetric DDoS (origin still exposed).
- **Full:** add item 3 (Cloudflare proxy). The only option that actually addresses volumetric DDoS + origin-IP hiding, but touches DNS, TLS, and origin firewall together.

The user previously set `feed.` as a grey-cloud (DNS-only) CNAME deliberately during the domain migration — confirm whether that was intentional (e.g. dynamic-DNS friction) before flipping to orange.

---

## Live state (as found, names not secrets)

| Thing | Value |
|---|---|
| Host | `fox`, LAN `192.168.0.89` |
| Public origin IP | `68.84.4.134` (residential, via `elucia.tplinkdns.com` DDNS) |
| Public domains | `themorningfox.com` (broadsheet, nginx static `web/`), `feed.themorningfox.com/ai-digest` (digest, nginx static `feeds/ai-digest/`) |
| Internet-facing ports | 80, 443, 51820 (wireguard) — DBs/SSH LAN-only |
| nginx config | `/etc/nginx/` (world-readable conf); no rate limiting |
| fail2ban | active; jails `nginx-env`, `sshd` |
| Firewall | iptables INPUT policy ACCEPT (no ufw, no default-deny) |
| Audit doc | `~/security-audit-2026-06-16.md` |

---

## How to resume

1. **Sanity check (read-only first):** `dig +short themorningfox.com feed.themorningfox.com`, `sudo iptables -L INPUT -n`, `sudo fail2ban-client status`, `grep -rn "limit_req\|limit_conn" /etc/nginx/`. Confirm the findings above still hold (home IP may have rotated).
2. Read `~/security-audit-2026-06-16.md` for the broader hardening context (firewall + nginx items overlap with this doc).
3. Get the path decision (Minimal vs. Full) from the user before any change.
4. If implementing: start with item 1 (nginx `limit_req`), `nginx -t` before every reload. Item 3 should get its own written plan because it bundles DNS + TLS + origin-firewall changes.
5. These are infra changes on `fox` (`/etc/nginx`, iptables, Cloudflare DNS) — **not** repo code. Confirm with the user before editing host config or DNS.

---

## Out of scope this session (NOT touched)

- **Uncommitted repo work is unrelated to this handoff.** Working tree on `dev` (HEAD `518d4d5`) has modified `jina_clone/briefing/feed.py` (this session's feed-page changes: broadsheet link moved to bottom, "Past editions" picker added, clickable masthead logo) plus pre-existing modifications (`.env.example`, `CLAUDE.md`, `web/*`, etc.) and many untracked `briefings/*.json` runtime artifacts. None of that relates to DDoS work. ⚠️ Do **not** `git add -A` in this repo (it has swept runtime artifacts into a feature commit before — see CLAUDE.md).
