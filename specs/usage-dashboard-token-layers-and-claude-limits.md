# Spec: Fleet token ledger (provider / model / project layers) and Claude quota meters on codexusage.pitchai.net

Status: approved for build 2026-10-05 · branch `feat/usage-layers-claude-limits-20261005` · scope: monitoring repo only

## Original request (verbatim)

"""on ssh 135.181.182.48 we have the agent engine which is multinode (one master several nodes) cli + app-servers for
different providers (where the agents actually run in) + databases + control planes + drainer and reminder and event
inbox services. all designed to run agents. deeply study the multi-platform and multiservice code. important to
understand is also the auth account rotation and the usage dashboard mainly. "https://codexusage.pitchai.net/" is the
dahsboard. so you must open new brnach to dashboard. and on there we want to be able to see in addition to current also
layered by provider how many tokens we used, layered by model and layered by project. with them disableable and
enableable. so that must be tracked and visualized without hurting performance. also claude accounts currently don't
show their usage/limits like codex accounts do but they shou;ld so fix that and show the remaining percentage for them
to somehow. first write spec and then build it, normally this does not require agent engine changes and only codex usage
dashbaord changes."""

## Summary

Two additions to the existing Codex capacity dashboard. Neither changes Agent Engine code, cells, owners, the auth
broker, or Work Inbox:

1. **Fleet token ledger.** A new dashboard section charts how many tokens the whole engine fleet (master, jeff-dev,
   fsn1; every provider runtime) used, as three layers: **by provider**, **by model** and **by project**. Each layer
   panel can be switched on or off, and every series inside a layer can be hidden or shown from its legend.
2. **Claude quota meters.** Each Claude account shows real **5-hour and weekly remaining percentages with reset
   times**, like the Codex broker accounts. Today it shows a permanent "No usage reported yet".

## Study findings that drive the design (2026-10-05)

### Where agents run and where tokens are recorded

| Node | Cells | Runtimes producing tokens |
|---|---|---|
| master 135.181.182.48 | dev-main-cell-one, dev-monitoring-cell | managed Codex app-server (account broker), DeepSeek owner, API owners (opencode_go → Xiaomi MiMo, zcode_account → Zhipu GLM), Claude owner, astra owners; ORI voice (`/root/.codex`) |
| jeff-dev 94.130.17.246 | dev-jeff-cell-two | managed Codex app-server (largest producer), DeepSeek, API owners, Claude owner (idle) |
| fsn1 144.76.61.162 | pitchai-fsn1-01 | managed Codex app-server; DeepSeek/API/Claude owners idle |

- **No central store holds token usage today.** Central Postgres has no token columns. Events Bus goal events carry
  project/provider but no tokens. The fleet-metrics collector is CPU/memory/disk only. The control-plane table
  `scheduling_decision_outcome` stopped recording tokens on 2026-09-30, and it repeats one turn across decisions.
  The broker's `daily_usage_buckets` are per Codex account and include non-engine use.
- **Every runtime writes codex-format rollouts**: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`.
  - `session_meta` carries the thread id and cwd.
  - `turn_context` carries `model` and `effort`.
  - `event_msg/token_count` carries the token usage of each model request.
  - Codex-family runtimes report a cumulative `total_token_usage`. The usage of a request is the delta; an unchanged
    total is a duplicate event, and a forked file starts from 0.
  - The Claude owner reports only `last_token_usage` per SDK result. Its input includes cache reads/creation, it has
    no reasoning tokens, and `model` is the alias (`opus`, `sonnet`, `fable`, `haiku`).
- **CODEX_HOMEs**:
  - Managed app-server: `process_env.CODEX_HOME` in `/tmp/paas-*/.managed-app-server-systemd-launch-v1-*.json`.
  - Owners: `/var/lib/pitchai-cli-new/{astra,deepseek,api,claude}-owners/*/codex-home`. `owner.json .provider` names
    the route.
- **Provider is derived from the model id**: gpt → OpenAI, opus/sonnet/haiku/fable/claude → Anthropic,
  deepseek → DeepSeek, glm → Zhipu, mimo → Xiaomi. `session_meta.model_provider` is unreliable because API owners
  proxy several vendors.
- **Project mapping is per cell**, in control-plane sqlite `agents(agent_id, thread_id, project_id, project_title,
  worktree_path)`. Owner lanes map through `agent_runtime_sessions.runtime_session_id` and
  `runtime_migrations.native_session_id`. Threads that resolve to nothing are counted as **(non-lane)**.
- **Volume**: about 100k `token_count` events per day fleet-wide, and 2–2.5 GB per day of new rollout bytes (about
  8 MB per 5 minutes; jeff-dev about 5 MB per 5 minutes). Hourly buckets are a few thousand rows per day.
- **Reachability**: master can ssh to jeff-dev. fsn1 is reachable from master only through fsn1's own outbound
  tunnel. Both workers can open ssh to master:22.

### Auth account rotation (context for the Claude meters)

- **Codex**: the `auth-token-server` broker (master, :38188) leases accounts. It drops disabled,
  last-resort-unless-allowed, exhausted, cooling-down and auth-invalid accounts, then ranks the rest by expiry, tier,
  reservations, preference, affinity and priority, with a weighted random pick. The five-hour floor
  `AUTH_TOKEN_SERVER_MIN_FIVE_HOUR_REMAINING_PERCENT` is 0 in production. The broker polls
  `chatgpt.com/backend-api/wham/usage`, and the dashboard reads its redacted `state.json`.
- **Claude**:
  - Each host's Claude owner (`/var/lib/pitchai-cli-new/claude-owners/<id>/`) holds 1–8 profile HOMEs in rotation
    order (`accounts.json`). The same three Anthropic Max accounts sit behind all three hosts, each host with its own
    credential copy.
  - A new conversation takes the first profile that is not limited and stays pinned to it.
  - A `rejected` rate-limit event cools the profile down until `resetsAt`; a 429 cools it for 900 s and a 401 for
    300 s.
  - The owner keeps only the latest rate-limit event per profile. That event carries `utilization` only for
    `allowed_warning`, so the dashboard's single `used_percent` is almost always null.
- **Real Claude utilization exists without generation.** The official Claude binary's `/usage` local command
  (`claude -p /usage --output-format json`) calls `GET /api/oauth/usage` and prints "Current session: N% used ·
  resets …" and "Current week (all models): N% used · resets …".
  - Verified on master on 2026-10-05: `local_command: "usage"`, `num_turns: 0`, zero input/output tokens.
  - The binary refreshes an expired access token itself, under its own `.oauth_refresh.lock`.
  - With `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` the run touches nothing except `.claude/sessions`: no
    account-skill sync. It then also skips refresh, so an expired token yields no limit lines.

## Goals

1. Token usage per hour for the whole fleet, by provider, model and project, for the last 24 hours, 7 days and 30 days.
2. Every layer, and every series inside a layer, can be disabled and re-enabled in the UI. The choice persists in the
   browser.
3. No measurable performance cost:
   - On the engine: read-only, incremental, niced/idle-IO exporters, with no engine process or DB write.
   - On the dashboard: pre-aggregated hourly rows, cached responses, and the ledger only fetched while shown.
4. Claude accounts show 5-hour and weekly remaining percent with reset times, plus model-scoped weekly limits when
   the provider reports them, refreshed every 5 minutes, with explicit stale/unavailable states.
5. No Agent Engine, owner, broker or Work Inbox code change.

## Non-goals

- Cost in currency. Subscription accounts have no per-token price, so the ledger counts tokens only.
- Changing routing, cooldowns or rotation. The dashboard stays read-only.
- Reconstructing history older than the rollouts still on disk. Hibernation/offload moved older rollouts away.
- Probing Claude on jeff-dev/fsn1. Their credential copies are separate, stale logins; refreshing them would only add
  risk.

## Design

### A. Token ledger exporter (`auth_usage_dashboard/token_ledger/`, stdlib-only, Python ≥ 3.10)

One package, used on the hosts by `python3 -m token_ledger` and inside the dashboard image for reporting.

- **`collect` (every node, systemd timer every 5 min)**:
  - Discovers CODEX_HOMEs: managed app-server manifests, the owner dirs, and configured extra homes (master:
    `/root/.codex` = ORI voice).
  - Tails new rollout bytes from a per-file cursor `(path, inode) → byte offset, last cumulative totals, current
    model/effort, thread id`.
  - Only lines whose first 160 bytes identify `session_meta`, `turn_context` or `event_msg/token_count` are
    JSON-decoded. A partial last line is never consumed.
  - Usage is computed as:
    - Codex family: the delta of `total_token_usage`. A repeat counts zero; a decrease is a counter reset.
    - Claude owner: the `last_token_usage` sum.
  - Each request's tokens go into the hour of its event timestamp: `(hour, node, cell, project, agent, provider, model,
    route)` → input, cached input, output, reasoning, total, requests.
  - The cursor advance and the bucket increments commit in **one SQLite transaction**, so every event is counted
    exactly once across crashes.
  - Thread → (cell, agent, project) is resolved from each cell's control-plane sqlite in read-only mode with a 15 s
    busy timeout. A cached map is refreshed at most every 10 minutes, and only when an unknown thread appears.
  - **Budget per run: 192 MiB of rollout bytes and 150 s.** Remaining bytes continue next run, so the first-time
    backfill (default 30 days by file mtime) spreads over hours without load spikes.
  - systemd: `Nice=15`, `IOSchedulingClass=idle`, `CPUQuota=50%`, `MemoryMax=512M`.
- **Node-local state** lives in `/var/lib/pitchai-token-ledger/ledger.sqlite3` (WAL, 0600): cursors, hourly rows with
  a monotonically increasing `change_seq`, thread map, and push cursor.
- **Delivery to master**:
  - Master's own run calls the ingest in-process.
  - Workers pipe NDJSON of rows with `change_seq > last_acked` over ssh. The target is a **forced-command,
    `restrict`ed key** in master root's `authorized_keys` that can only run
    `python3 -m token_ledger ingest --node <name>`. The node name is pinned by the key, not taken from the payload.
  - Rows carry absolute hourly values, so ingest is an idempotent upsert, and a failed push simply retries next run.
- **Fleet store** is `/srv/codex-usage-dashboard/token-ledger.sqlite3` (root 0600, WAL). It has the table
  `token_usage_hourly` keyed by `(hour_epoch, node, cell, project, agent, provider, model, route)` with an
  `hour_epoch` index, and the table `ledger_nodes` with last collect/push time, version, backlog bytes and source
  count. The dashboard container already mounts this directory.

### B. Dashboard API: `GET /api/v1/token-usage?range=24h|7d|30d` (SSO-protected like every account route)

- Buckets: 24h → 1 h, 7d → 3 h, 30d → 1 day, UTC-aligned, current bucket partial.
- One response returns all three dimensions:
  - Each dimension holds up to 7 named series plus **Other**, ranked by total.
  - Each series has totals (total, input, cached input, output, reasoning, requests) and point arrays for the metrics
    `total` (all tokens), `fresh` (total − cached input) and `output`.
- Provider colors are fixed per provider. Model and project colors follow rank within the range.
- The response also carries `coverage.sources` (one per node, stale after 20 minutes), the backfill backlog, and a
  method note.
- Read-only SQLite query in a worker thread, with a **60 s in-memory cache per range**. Measured cost is in the tests;
  the 30d query covers about 150k rows.
- Missing or invalid store → explicit `error`; never invented zeros.

### C. Dashboard UI (`static/token_usage.js`, section "Tokens used by provider, model and project")

- **Controls**, in one row: range (24 hours / 7 days / 30 days), measure (all tokens / uncached input + output /
  output), and layer checkboxes (By provider / By model / By project).
- A **Hide ledger** button collapses the section and stops all ledger fetching.
- Each layer is a stacked column chart:
  - Thin columns, 2px surface gaps, and a validated categorical palette, with Other in neutral grey.
  - Legend chips toggle series; hidden series keep their colors.
  - Hovering or focusing a column shows a tooltip with every visible series at that bucket.
  - A totals table (tokens, share, input, cached input, output) is the accessible table view.
- Preferences (enabled, range, measure, layers, hidden series) persist in `localStorage` under try/catch.
- The ledger polls every 60 s only while it is shown and the tab is visible. The existing 30 s capacity poll is
  untouched.

### D. Claude quota meters

- **Exporter** `claude_accounts.py` (master, existing 1-minute timer). Per profile, at most every 5 minutes, it runs
  the **pinned official binary**:
  `claude -p /usage --output-format json --no-session-persistence --strict-mcp-config --setting-sources user`.
  - HOME is the profile, cwd is an empty temporary directory, and the environment is scrubbed with `TZ=UTC`,
    `DISABLE_AUTOUPDATER=1` and first `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
  - If that returns no limit lines (expired token), it retries once without the flag so the binary refreshes under its
    own lock.
  - **Fail-closed guard**: a result that is not `local_command == "usage"` with zero turns and zero tokens disables
    probing (guard file) and is reported. The probe never sends a prompt to a model.
  - It parses `Current session` → `five_hour`, `Current week (all models)` → `seven_day`, `Current week (Sonnet only)`
    → `seven_day_sonnet` and `Current week (<model>)` → model-scoped. Each becomes `{used_percent, remaining_percent,
    resets_at}`.
  - Readings carry over between probes, with `quota_observed_at`.
  - The order within one run is **`/usage` first, then `auth status`**. An expired token's `auth status` leaves a fresh
    `.oauth_refresh.lock`, which stalled the immediately following refresh during the study.
  - The exporter itself never opens credential files.
- **Snapshot** stays `schema_version: 1`, with additive fields, so the old container and old deploy checks keep
  working during the rolling replace:
  - New fields: `windows`, `scoped_windows`, `quota_observed_at`, `quota_error`.
  - `used_percent`/`window` are set to the tightest reported window.
- **Route** `/api/v1/claude-accounts` passes `windows` through with remaining %, reset ISO time and stale flags. A
  quota older than 15 minutes is stale.
- **UI**: per account, one meter for the 5-hour window and one for the weekly window ("N% left · resets …"), plus a
  small line per model-scoped week. A window at 100% shows "Limit reached · resets …".

## Safety and performance invariants

- Exporters never write to engine directories or databases.
  - Cell sqlite is opened `mode=ro` with a busy timeout, and only small `agents`/`agent_runtime_sessions`/
    `runtime_migrations` lookups run.
  - Rollouts are opened read-only.
- No secrets in any ledger or snapshot: rollout content, prompts and tool output are never stored, only token counts
  and ids. The Claude exporter reads only the binary's stdout.
- The dashboard container stays read-only, capability-free and mount-limited. The only new readable file is
  `token-ledger.sqlite3` in its existing data mount.
- Exporters use idle IO priority with CPU and memory caps, and a byte budget per run.
- The UI does no extra work when the ledger is hidden.

## Rollout

1. Deploy on master:
   - Install the `token_ledger` package plus `token-ledger-export.{service,timer}`, and the updated Claude exporter.
   - Deploy the dashboard image via `ops/deploy_codex_usage_dashboard.sh`, which gains a token-usage endpoint check.
2. Install workers (`ops/install_token_ledger_node.sh <node>`), each with its own ssh key and a forced-command line on
   master:
   - jeff-dev from master.
   - fsn1 from an operator machine.
3. Verify:
   - `python3 -m token_ledger status` on each node.
   - Fleet store node rows.
   - `/api/v1/token-usage` coverage of 3/3 nodes.
   - Claude cards showing 5h/weekly meters.

## Open risks

- Rollouts moved away by hibernation are not counted. The ledger counts from what is on disk, and the UI says so.
- The `/usage` text format is a Claude Code UI string. The parser is strict: unknown lines are ignored, and missing
  windows stay unknown, never 0% or 100%. The pinned binary changes only with owner releases.
- jeff-dev/fsn1 Claude credential copies are stale clones (secondary/third share refresh tokens across those two
  hosts). They are not probed, but any future Claude lane there may hit a revoked token. That is an engine follow-up,
  not part of this change.
