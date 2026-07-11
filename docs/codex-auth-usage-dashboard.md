# Codex authentication-broker capacity dashboard

`https://codexusage.pitchai.net` is the protected operator view for the authoritative Codex authentication broker on `pitchai-dev`.

## Architecture

- Nginx terminates TLS and requires the PitchAI tools HTTP Basic Auth file.
- Nginx injects `X-PitchAI-Operator` only after successful authentication.
- The dashboard listens only on `127.0.0.1:8124` and rejects UI/API requests without that trusted header.
- The container mounts `/srv/auth-token-server/data/accounts` read-only and reads only `metadata.json` and `state.json`. It never opens `auth.json`.
- The broker admin token is passed only to the container process so it can trigger the broker's account usage probe endpoint. It is never returned, logged, or embedded in the page.
- `/healthz` is intentionally unauthenticated and exposes only service health, generation time, and a stale boolean. All account-bearing routes require authentication.

The broker state files are root-only (`0600`). The production container therefore runs as container root with all Linux capabilities dropped, `no-new-privileges`, a read-only root filesystem, a small temporary filesystem, and only the broker accounts directory mounted read-only. The app has no endpoint that reads arbitrary files.

## Freshness and probe cost

The service rereads broker state every 15 seconds and runs a no-generation usage probe at most once every 5 minutes. A manual refresh is throttled to one probe per minute.

The probe calls the broker's existing `POST /v1/admin/accounts/{id}/probe` endpoint. That endpoint refreshes auth if needed and calls the Codex usage endpoint; it does not submit a prompt or run a model generation. The dashboard deliberately discards the secret-bearing admin response body and rereads only redacted state files.

This keeps quota metadata current without creating synthetic model work. Reducing the probe interval below five minutes is discouraged because it increases provider and auth traffic without improving operator decisions.

## Capacity model

One normalized capacity point equals one percentage point of a five-hour account window. One full account window is therefore 100 points.

- Current headroom contributes the measured remaining five-hour percentage for fresh, selectable accounts.
- A five-hour reset inside the selected horizon contributes 100 scheduled points when auth and weekly state permit it.
- Weekly exhaustion is a hard block until the weekly reset and is never converted into five-hour capacity.
- The 1-hour, 6-hour, and 24-hour percentages compare usable points with the configured pool's theoretical points over that horizon. They are an operational ceiling, not a token forecast or guaranteed throughput.
- Stale, auth-invalid, disabled, and unknown accounts do not contribute usable points.
- The broker safety floor is honored. An account at or below `AUTH_TOKEN_SERVER_MIN_FIVE_HOUR_REMAINING_PERCENT` is shown as five-hour limited even if the provider still reports a small remainder.

Reset credits use the provider's `rate_limit_reset_credits` metadata. The UI shows all dates returned by the provider. When the provider returns only `available_count`, the dashboard says that dates are unavailable rather than inventing them.

## Operations

Build and deploy the container from the repository root:

```bash
sudo ops/deploy_codex_usage_dashboard.sh
```

The script is intentionally host-locked to `pitchai-dev`. It validates the broker service and root-only credential source, builds an immutable Git-SHA image, starts a read-only canary on loopback without probing, checks the redacted API, and then replaces the production container with automatic rollback to the previous image if the post-check fails.

Post-deploy checks:

```bash
curl --fail --silent http://127.0.0.1:8124/healthz
curl --fail --silent -H 'X-PitchAI-Operator: deployment-check' \
  http://127.0.0.1:8124/api/v1/capacity | jq '.summary'
docker inspect codex-usage-dashboard --format '{{.State.Status}} {{.State.Health.Status}}'
```

Do not print the full API response in shared logs. It contains account labels and usage state, though it contains no credentials.

## Nginx, DNS, and access

- DNS: `codexusage.pitchai.net` A record to the public IPv4 address of `pitchai-dev`.
- HTTP bootstrap source: `ops/codexusage.pitchai.net.bootstrap.nginx.conf`.
- Nginx source: `ops/codexusage.pitchai.net.nginx.conf`.
- Basic Auth file: `/etc/nginx/htpasswd-pitchai-tools-dashboard`.
- TLS: Certbot-managed certificate for `codexusage.pitchai.net`.
- Certificate renewal: `ops/renew_codexusage_certificate.sh` through the committed systemd service and timer.
- External canary: the monitoring service checks the redacted `/healthz` response, DNS, TLS, and browser reachability. Docker performs the local container health check on `pitchai-dev`.

The same PitchAI tools dashboard credentials provide access. Never place a password in this repository, PM notes, screenshots, logs, or Telegram.

For a first deployment, install and enable the HTTP bootstrap vhost, run `nginx -t`, and reload Nginx before requesting the certificate. Once the certificate exists, replace the bootstrap file with the final Nginx source, validate again, and reload. This keeps the ACME challenge reachable without making Nginx depend on a certificate that has not been issued yet.

The host's legacy Certbot Python environment is not used for this certificate. Install `ops/renew_codexusage_certificate.sh` as `/usr/local/sbin/renew-codexusage-certificate`, install the two committed unit files in `/etc/systemd/system`, then enable `codexusage-cert-renew.timer`. The script pins the working official Certbot container image and renews only this certificate; it reloads Nginx only when the certificate fingerprint changes.

## Rollback

To redeploy a known image:

```bash
sudo ops/deploy_codex_usage_dashboard.sh codex-usage-dashboard:<git-sha>
```

For an Nginx rollback, restore the timestamped backup beside `/etc/nginx/sites-available/codexusage.pitchai.net`, run `nginx -t`, and reload Nginx. DNS removal is not needed for a short application rollback; the protected proxy can return a controlled maintenance response while the prior container is restored.

## Data safety invariants

- No `auth.json`, access token, refresh token, broker token, password, device code, callback code, or mailbox code may enter the API, DOM, logs, screenshots, tests, or repository.
- Active requester/session counts are informational telemetry only. They never reduce account availability.
- Only actual auth validity, provider rate/quota state, disabled state, freshness, and the broker safety floor affect displayed selectability.
