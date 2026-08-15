# P11 follow-up — Metrics/Alerting Operationalization

Wires the export surface [19-metrics-and-alerting.md](19-metrics-and-alerting.md)
built ("metric emission is implemented and tested; alert delivery is an
external dependency") into a real, running local Prometheus + Alertmanager,
and proves the whole chain end to end against live infrastructure. This does
**not** change anything about the P11 verdict in
[21-p11-acceptance-report.md](21-p11-acceptance-report.md) — it operationalizes
a dependency that document explicitly named as external and un-built.

**No application code changed.** Everything here is new configuration
(`infrastructure/prometheus/`) plus this document — `backend/app/metrics.py`
and the P11 admission-control/metrics code are untouched.

## Architecture

**Prometheus and Alertmanager both run as local macOS processes, not inside
docker-compose.** Reasons, not just a preference:

- Alertmanager was already stood up this way (Homebrew-installed binary,
  `~/alertmanager/alertmanager.yml`, port 9093) before this work started.
- The ADOS backend publishes port 8000 to the host identically whether it's
  started bare (`scripts/run-backend.sh`) or via `docker compose up backend`
  — either way `localhost:8000/metrics` is the correct, reachable scrape
  target from this machine. There is no networking reason to containerize
  Prometheus.
- Running Prometheus the same way as the already-running Alertmanager avoids
  building two competing topologies (one host-local, one containerized) for
  a single scrape target — the task's own explicit instruction not to create
  competing architectures.

```
ADOS backend (:8000/metrics)
        │  scrape, 15s
        ▼
Prometheus (:9090, local process)
        │  alert rules evaluated every 15s
        ▼
Alertmanager (:9093, local process)
        │  webhook, group_wait 10s
        ▼
infrastructure/prometheus/webhook_receiver.py (:9095, local process)
```

Repo-owned files (reproducible by another developer):

| File | Purpose |
|---|---|
| `infrastructure/prometheus/prometheus.yml` | Scrape config (`job_name: ados` → `localhost:8000`) + Alertmanager forwarding target |
| `infrastructure/prometheus/alert_rules.yml` | 16 alert rules, one per row of doc 19's alerting contract table |
| `infrastructure/prometheus/alertmanager.yml` | Canonical Alertmanager config — local-only webhook receiver |
| `infrastructure/prometheus/webhook_receiver.py` | Minimal stdlib HTTP server proving delivery; logs to `webhook_receiver.log` next to it |

Alertmanager's actual running config lives outside this repository
(`~/alertmanager/alertmanager.yml`, a per-machine path, not `git`-tracked) —
the file above is copied over it, then applied live via `POST /-/reload`
(Alertmanager's own reload endpoint), never by killing/restarting the
process. This kept the developer's already-running foreground Alertmanager
instance untouched rather than terminating a process running in their own
terminal session.

## How Prometheus discovers ADOS

Static config, not service discovery — appropriate for one target on one
host: `infrastructure/prometheus/prometheus.yml`'s `scrape_configs` names
`job_name: "ados"`, `static_configs: [{targets: ["localhost:8000"]}]`,
`metrics_path: /metrics`. `GET /metrics` is unauthenticated (matches
`/healthz`'s posture — see doc 19's "Access" section), so no
`bearer_token`/`basic_auth` block is needed in the scrape config.

## Starting / restarting each process

**Prometheus** (not a brew service in this setup — run directly so the repo
config is unambiguously the one in effect):

```bash
cd infrastructure/prometheus
prometheus --config.file=prometheus.yml \
  --storage.tsdb.path=<a local, non-repo data directory> \
  --web.listen-address=127.0.0.1:9090
```

Restart: kill the process and re-run the same command — Prometheus reloads
`prometheus.yml` and `alert_rules.yml` from disk on start. To pick up a
config change *without* restarting: `curl -X POST http://127.0.0.1:9090/-/reload`
(same as Alertmanager's reload endpoint below) or `kill -HUP <pid>`.

**Alertmanager** (already running as documented above):

```bash
alertmanager --config.file=<path to alertmanager.yml>
```

Restart: kill and re-run, or reload without restarting:

```bash
curl -X POST http://localhost:9093/-/reload
```

**Webhook receiver** (local dev/verification tool only):

```bash
python3 infrastructure/prometheus/webhook_receiver.py 9095
```

## Verifying the chain

**1. ADOS target is UP:**

```bash
curl -s http://127.0.0.1:9090/api/v1/targets | python3 -m json.tool
```

Look for `"job": "ados"`, `"health": "up"`. `"health": "down"` with
`"lastError": "server returned HTTP status 404 Not Found"` means the running
ADOS process predates the `/metrics` route (P11) — rebuild/restart it from a
current checkout, not a stale image.

**2. ADOS metrics are actually being scraped:**

```bash
curl -s http://127.0.0.1:9090/api/v1/query?query=up{job=\"ados\"}
```

`value` of `1` confirms it; cross-check against `curl -s http://localhost:8000/metrics`
directly to confirm the endpoint itself is serving real Prometheus text.

**3. An alert is firing:**

```bash
curl -s http://127.0.0.1:9090/api/v1/alerts | python3 -m json.tool
```

**4. Prometheus forwarded it to Alertmanager:**

```bash
curl -s http://localhost:9093/api/v2/alerts | python3 -m json.tool
```

Same `alertname`/labels should appear, independently reported by Alertmanager
rather than trusted from Prometheus's own view.

**5. Alertmanager delivered it:**

```bash
cat infrastructure/prometheus/webhook_receiver.log
```

Each line is one delivered payload, including `status` (`firing`/`resolved`)
and the alert's labels — independent proof of delivery, not just that
Alertmanager's internal state says it routed somewhere.

**6. Inspecting Alertmanager state generally:**

```bash
curl -s http://localhost:9093/api/v2/status | python3 -m json.tool   # config in effect, uptime, cluster status
curl -s http://localhost:9093/api/v2/alerts | python3 -m json.tool   # current alerts, firing or resolved
```

## Configuring a real receiver later

`infrastructure/prometheus/alertmanager.yml`'s `local-webhook` receiver is
**not a production notification channel** — it's a loopback-only HTTP
listener that exists to prove delivery. An operator wiring this up for real
paging would replace (not add alongside) that receiver block with a real
one, e.g.:

```yaml
receivers:
  - name: ops-team
    slack_configs:
      - api_url: <secret, from a secret store, never committed>
        channel: "#ados-alerts"
```

or `email_configs`/`pagerduty_configs`/etc. per Alertmanager's own
documentation. This repository deliberately does not make that choice for an
operator — see doc 19's scope boundary and this document's own "Limitations"
section below. No such receiver was configured or sent to as part of this
work, per explicit instruction.

## Evidence from the live proof run (2026-08-12)

All of the below is real, against real local infrastructure — no mocking of
Prometheus/Alertmanager/HTTP involved anywhere in this phase.

**Config validation:**
```
$ promtool check config infrastructure/prometheus/prometheus.yml
  SUCCESS: 1 rule files found
  SUCCESS: prometheus.yml is valid prometheus config file syntax
Checking alert_rules.yml
  SUCCESS: 16 rules found

$ promtool check rules infrastructure/prometheus/alert_rules.yml
  SUCCESS: 16 rules found

$ amtool check-config infrastructure/prometheus/alertmanager.yml
Checking 'alertmanager.yml'  SUCCESS
Found: global config, route, 0 inhibit rules, 1 receivers, 0 templates
```

**An incidental, real end-to-end proof happened before any deliberate
trigger:** the ADOS backend container running at the time was a pre-P11
image (built 2026-08-11, before `backend/app/routers/metrics.py` existed),
so Prometheus's first scrapes genuinely 404'd. `ADOSTargetDown` fired for
real, reached Alertmanager, and was delivered to the webhook receiver —
then, once the image was rebuilt from current source and the container
recreated, the target came back `up` and the alert delivered a `resolved`
notification. This is unstaged proof of the full chain, including
resolution, using a real failure rather than a synthetic one.

**Deliberate trigger** (`ADOSAuthFailureRateHigh`, 21 failed `/auth/login`
attempts against a nonexistent username — a safe, real code path with no
account-lockout mechanism and no external side effects):
- `ados_authentication_failures_total` incremented by exactly 21.
- Rule went `pending` → `firing` in Prometheus after the configured `for: 1m`.
- Alertmanager's `/api/v2/alerts` independently showed the same alert.
- `infrastructure/prometheus/webhook_receiver.log` recorded the `firing`
  delivery, and later a `resolved` delivery once the 5-minute `increase()`
  window aged past the burst — a complete, deliberately-triggered
  fire→deliver→resolve→deliver cycle.

**Negative controls** (each: mutate → observe the expected failure →
revert → `shasum -a 256` confirms byte-identical restoration → confirm
recovery):

| Control | Mutation | Observed failure | Restored | Recovery confirmed |
|---|---|---|---|---|
| Wrong scrape target | `ados` job target → `localhost:59999` | Target `health: down`, `lastError: ... connection refused` | SHA-256 matched pre-mutation hash | Target back to `health: up` next scrape |
| Broken alert rule | Malformed PromQL in `ADOSTargetDown`'s `expr` | `promtool check rules` failed with a parse error; **live Prometheus reload also refused it** (`"error loading rules, previous rule set restored"`), keeping all 16 valid rules active throughout | SHA-256 matched pre-mutation hash | `promtool check rules` passed again (16 rules); live reload succeeded |
| Broken Alertmanager destination | Webhook URL → `127.0.0.1:9096` (nothing listening) | `alertmanager_notification_requests_failed_total{integration="webhook"}` rose from 0 to 8; `webhook_receiver.log` did not grow while broken | SHA-256 matched pre-mutation hash (both the repo copy and the live `~/alertmanager/alertmanager.yml`) | `webhook_receiver.log` grew again immediately after the fix + reload |

No mutation was left in place; every file's final SHA-256 matches its
pre-mutation value.

**Label safety:** every alert fired during this run carried only
`alertname`, `instance`, `job`, `severity` — no token, session id, mission
id, or free-text argument ever appeared in a label, matching doc 19's own
proof for the underlying metrics.

## Limitations of this local setup

- **Single process, no HA.** One Prometheus, one Alertmanager, no
  clustering, no long-term storage — matches Model A's single-process
  envelope (doc 18 §5), not a claim of anything beyond it.
- **No real notification channel.** The webhook receiver proves the pipe
  works; it does not page anyone. Standing up a real receiver is a separate,
  explicitly-deferred decision (previous section).
- **`prometheus.yml`'s scrape target is a static host:port**, not service
  discovery — correct for "one ADOS process on one known host," not a
  multi-host or containerized-Prometheus deployment.
- **Two known rule-level approximations**, both already flagged in
  `alert_rules.yml`'s own comments, not new information here:
  `ADOSMissionPossiblyStuck` (no mission-duration correlation available) and
  `ADOSSessionActivityAdmissionRejections` (fires in aggregate; doc 19
  deliberately carries no per-session label).
- **Retention/storage/backup for Prometheus's own TSDB is out of scope** —
  the data directory used for this work is a scratch location, not a
  durable one; a real deployment needs its own decision here, same posture
  as doc 18 §16.3 already took for Postgres backups.
- **This is local development tooling, not a production monitoring
  deployment** — do not read anything in this document as a readiness claim
  beyond "the wiring works, proven against live infrastructure once."
