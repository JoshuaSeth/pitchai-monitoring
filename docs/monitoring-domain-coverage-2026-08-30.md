# Monitoring domain coverage sweep — 2026-08-30

## Result

The nine-day sweep found one new production site with two public host
contracts: `formatiefleren.nl` and its canonical `www` redirect. Both are live,
owned, and actionable, so both use normal critical incident routing.

The reconciled inventory contains **71 active domains**, **16 groups**, and
**37 explicit exclusions**. Of the active entries, **65 use normal critical
incident routing** and **six are dashboard-only**. All active names are unique,
all exclusions are unique, and the two sets do not overlap.

Four recurring candidates are now explicit exclusions:
`events.pitchai.net`, `mockopenai.pitchai.net`, `aipc.skybuyfly.com`, and
`unimixbr.netlify.app`. This keeps undeployed, internal, invalid-certificate,
and replaced origins out of alert routing without hiding their classification.

## Evidence window

The exact window was `2026-08-21T20:46:51Z` through
`2026-08-30T20:46:51Z`.

- The central live-agent index reported complete byte coverage across all
  three cells. It covered 427 agent/session sources and 672,254 messages in the
  window; 20,515 messages contained domain-oriented candidate text.
- PM DB contained 488 updated tasks across 36 projects. Of those, 338 tasks
  across 35 projects contained domain-relevant evidence. The project mapping
  inventory contained 71 mappings to 57 distinct repositories.
- The bounded local source scan covered 604 unique recent commits across nine
  available repositories, including infrastructure, monitoring, DFT-adjacent,
  AI Price Crawler, work-inbox, CLI, and document-runtime changes.
- The Namecheap lane confirmed that `pitchai.net` remained at 72 records after
  the 2026-08-28 DNS work. The new `formatiefleren.nl` zone contains exactly an
  apex A record and a `www` CNAME.
- Live DNS, TLS, redirect, and HTTP probes were repeated on 2026-08-30 before
  changing the inventory.

The pre-change monitoring deployment ran image
`service-monitoring:a17e7eefb599a6bd760e4e5d0621459ba11a6d78` with the
monitor, E2E registry, E2E runner, and database dependency monitor all running
with zero restarts. The protected dashboard returned HTTP 200.

## New actionable contracts

| Host | Evidence | Classification |
|---|---|---|
| `formatiefleren.nl` | Namecheap A `135.181.182.48`; valid TLS; final HTTP 200; title `DFT · Toetsen in dienst van leren · Zacht en mensgericht`; production/staging image SHA `f6e7587aeda4142ec36836a4323008a2f7dd04b5` | Active, production, critical |
| `www.formatiefleren.nl` | Namecheap CNAME to the apex; valid TLS; HTTP 301 to `https://formatiefleren.nl/`, then final HTTP 200 with the same DFT content | Active alias, production, critical |

The apex and alias can fail independently at DNS, TLS, or redirect layers.
Keeping both actionable matches the existing PitchAI and Unimix apex/alias
contracts and protects the public launch path without creating duplicate
inventory entries.

## Explicit exclusions added

| Host | Observation | Classification |
|---|---|---|
| `events.pitchai.net` | Authoritative NXDOMAIN. The deployed events bus contract is `https://pitchai.net/events-bus`; production Graph subscriptions use that route. | Pending/unprovisioned; no alert |
| `mockopenai.pitchai.net` | Authoritative NXDOMAIN. DFT staging uses an in-process `/__llm_mock_openai` route and internal mock container. | Internal-only; no alert |
| `aipc.skybuyfly.com` | DNS resolves and an insecure probe reaches a legacy endpoint, but ordinary TLS validation fails and the AIPC runtime audit confirms it is not a certificate-covered public hostname. | Invalid alias; monitor `skybuyfly.pitchai.net` |
| `unimixbr.netlify.app` | Historical Netlify origin still returns 200, but the repaired public contracts are the monitored `unimixbrasil.com.br` apex and `www` alias. | Replaced origin; no alert |

## Other candidates rejected as noise or non-owned

- `app.pitchai.net`, `autopar.demos.pitchai.net`, `cms.deplanbook.nl`,
  `orthopars.pitchai.net`, and `proof.pitchai.net` occur only in tests,
  historical reports, or verifier fixtures and are NXDOMAIN.
- `app.doorstroomtoets.nl` and
  `app-staging-no-spend.doorstroomtoets.nl` remain explicitly not owned or
  operated by PitchAI/DFT and were already in the exclusion ledger.
- `geloofsverdediging.nl` is an existing third-party WordPress site that the
  relevant deployment work was required not to disturb. It is not a PitchAI
  monitoring target.
- Mail, vendor, documentation, package, temporary tunnel, and example
  hostnames were rejected before inventory comparison.

## Final active inventory

```text
2fa-server.37.27.67.52.nip.io
aardappelprijs.nl
afasask.gzb.nl
afasask.pitchai.net
agentcloud.pitchai.net
aigenda-monitor.pitchai.net
aigenda-rules.demos.pitchai.net
aigenda.pitchai.net
akkerbouwprijs.nl
apologetica-wagtail-staging.pitchai.net
assets.pitchai.net
auth.autopar.pitchai.net
auth.pitchai.net
autopar-staging-web.37.27.67.52.nip.io
autopar.pitchai.net
breakglass.pitchai.net
chat.pitchai.net
cms.deplanbook.com
codex-cowork.pitchai.net
codex-voice.pitchai.net
codexusage.pitchai.net
cursussen.pitchai.net
dashboards.pitchai.net
demo.afasask.pitchai.net
deplanbook.com
deplanbook.pitchai.net
dft-marketing-staging.pitchai.net
digibeat.demos.pitchai.net
dispatch.pitchai.net
dpb.pitchai.net
filedrop.pitchai.net
formatief-toetsen.pitchai.net
formatiefleren.nl
hetcis.nl
jeff-codex-voice.pitchai.net
jeff-dispatch.pitchai.net
jeff-work-inbox.pitchai.net
lfs.pitchai.net
livedocuments.pitchai.net
monitoring.pitchai.net
navigation.pitchai.net
onboarding-course.pitchai.net
orthoparse.pitchai.net
pitchai.net
potaito.pitchai.net
privacy-gateway-staging.pitchai.net
privacy-gateway.pitchai.net
registry.pitchai.net
route-anchor.pitchai.net
servers.pitchai.net
skybuyfly.pitchai.net
stable.skybuyfly.pitchai.net
staging.afasask.pitchai.net
staging.autopar.pitchai.net
staging.chat.pitchai.net
staging.formatief-toetsen.pitchai.net
staging.hetcis.pitchai.net
staging.potaito.pitchai.net
storage.pitchai.net
studentenreisproduct.demos.pitchai.net
suggestions.pitchai.net
support.pitchai.net
theplanbook.pitchai.net
tools.pitchai.net
unimixbrasil.com.br
whatsapp.pitchai.net
wiki.pitchai.net
www.formatiefleren.nl
www.hetcis.nl
www.pitchai.net
www.unimixbrasil.com.br
```

## Scheduling and communication boundary

The recurring reminder remains active on a 259,200-second interval. Its next
scheduled fire is `2026-09-02T20:44:32.573496Z`.

This reminder fire explicitly withheld authority for Telegram and every other
outgoing message. No Telegram, email, WhatsApp, client, vendor, group, or
public message was sent. The repository evidence and the direct completion
response are the only reports produced by this fire.
