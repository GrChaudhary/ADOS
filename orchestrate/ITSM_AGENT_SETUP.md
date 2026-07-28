# SOP: Standing up a dedicated ADOS ITSM agent

Replaces today's setup — every real ServiceNow write (`CREATE_INCIDENT`,
`CREATE_CHANGE_REQUEST`, `SCHEDULE_MAINTENANCE`, `NOTIFY_OPERATOR`) currently
routes through `ados_executive_copilot`
(`integrations/connectors/watsonx_itsm.py`'s `_INCIDENT_AGENT_ID`), an agent
that was originally built as a read-only KPI reporter and later had 32
ServiceNow tools bolted onto it by hand. Its ServiceNow connection is also
currently broken ("connections ServiceNow are not fully configured").

This SOP builds a small, dedicated `ados_itsm_agent` instead — two tools,
one purpose, pointed at a fresh ServiceNow Developer Instance (PDI) you
control — and rewires the connector to use it.

**Time:** ~15 minutes. **Requires:** the ADK CLI (already installed at
`.venv/bin/orchestrate`, already authenticated against the `dev` env — run
everything below with `cd ADOS && source .venv/bin/activate` or prefix
commands with `.venv/bin/`), and your ServiceNow PDI's admin username +
password.

---

## Step 0 — Confirm the CLI is ready

```bash
orchestrate env list          # `dev` should show as (active)
orchestrate agents list       # sanity check you can reach the tenant
```

If `dev` isn't active: `orchestrate env activate dev --api-key "$WO_API_KEY"`
(from `ADOS/.env`).

---

## Step 1 — Register a connection for the new ServiceNow instance

```bash
orchestrate connections add --app-id ados_servicenow_dev397690

orchestrate connections configure \
  --app-id ados_servicenow_dev397690 \
  --env draft \
  --type team \
  --kind basic \
  --url https://dev397690.service-now.com

orchestrate connections set-credentials \
  --app-id ados_servicenow_dev397690 \
  --env draft \
  --username admin \
  --password '<your PDI admin password>'
```

Repeat `configure` + `set-credentials` with `--env live` too — agents
invoked outside the builder's own test chat run against the `live`
environment's credentials, not `draft`'s.

**Do not put the real password in a script or commit it anywhere.** Type it
directly into the `set-credentials` command in your shell, or better, run it
without `--password` — the CLI will prompt interactively so it never lands
in shell history.

Verify: `orchestrate connections list` — `ados_servicenow_dev397690` should
show `✅` under Credentials Set for both `draft` and `live`.

---

## Step 2 — Review the tool code

Already written for you: [`orchestrate/servicenow_itsm_tools.py`](servicenow_itsm_tools.py)
— two tools, `create_incident` and `get_incident`, calling ServiceNow's
Table API directly over `urllib` (stdlib only, matching
`orchestrate/watsonx_tools.py`'s existing convention), authenticated via the
ADK's `get_application_connection_credentials()` against the connection
from Step 1. Already import-checked against the installed ADK.

If you registered the connection under a different `--app-id` than
`ados_servicenow_dev397690`, or the instance isn't `dev397690`, update the
two constants at the top of that file (`_APP_ID`, `_INSTANCE_URL`) to match
before continuing.

---

## Step 3 — Import the tools

```bash
orchestrate tools import -k python \
  -f orchestrate/servicenow_itsm_tools.py \
  -a ados_servicenow_dev397690
```

Verify: `orchestrate tools list` should show `create_incident` and
`get_incident`.

---

## Step 4 — Create the agent

```bash
orchestrate agents create --name ados_itsm_agent --kind native \
  --provider watsonx --llm "groq/openai/gpt-oss-120b" \
  --tools create_incident --tools get_incident \
  --instructions "You create and look up ServiceNow incident records on behalf of ADOS (Autonomous Defect & Orchestration System). Use create_incident to open a new incident — always pass a clear short_description and description built from the request. Use get_incident to look one up by number. After taking an action, end your reply with exactly one line in this exact format (no other text on that line): RESULT: {\"status\": \"created\", \"ticket_id\": \"<number>\", \"reason\": null} on success, or RESULT: {\"status\": \"failed\", \"ticket_id\": null, \"reason\": \"<short reason>\"} on failure. Never invent a ticket number — only report one a tool call actually returned." \
  --output orchestrate/ados_itsm_agent.agent.yaml
```

The `RESULT:` trailer convention matches what
`integrations/connectors/watsonx_itsm.py`'s `_parse_result_trailer()`
already expects — this keeps the connector unchanged in Step 6.

Verify: `orchestrate agents list` should show `ados_itsm_agent`.

---

## Step 5 — Verify it's actually connected (read-only)

Ask the agent to look up an incident that doesn't exist — this exercises
the real ServiceNow connection without creating anything:

```bash
orchestrate chat start   # or use the builder's test-chat UI for ados_itsm_agent
```

Ask it: *"Look up incident INC0000001."* You want a clean **"not found"**
style answer (proves the connection works), not *"connections ServiceNow
are not fully configured"* (proves it's still broken — recheck Step 1's
credentials, or check whether the PDI itself needs waking at
developer.servicenow.com → Manage).

---

## Step 6 — Point the connector at the new agent

In `integrations/connectors/watsonx_itsm.py`, get the new agent's ID from
`orchestrate agents list` (or the ID field in
`orchestrate/ados_itsm_agent.agent.yaml`), then update:

```python
_INCIDENT_AGENT_ID = "<ados_itsm_agent's real agent id>"
```

...and replace the comment above it (currently explaining the
`ados_executive_copilot` repurposing story) with a short note pointing at
this SOP instead. Hand this step to Claude with the new agent ID and it'll
make the edit and update the comment.

---

## Step 7 — Fire one real incident and verify

Same careful process used earlier in this project:

1. `POST /incidents` with a real scenario (e.g. the Line 2 Motor Housing one
   in `frontend-next/src/lib/demoScenario.ts`).
2. Poll `GET /incidents/{id}` to a terminal state — approve it if it lands
   at Tier 1 (`POST /incidents/{id}/approve`).
3. Confirm `capabilityInvoked` / `capabilityStatus` / the ticket number in
   the `CapabilityInvocationCompleted` event's `output`.
4. Independently confirm the ticket is real: call `get_incident` on that
   number yourself (via `orchestrate chat start` or a direct API call) —
   don't just trust the connector's self-reported success.

---

## After you're done

- **Rotate the ServiceNow admin password** you just typed into
  `set-credentials` if it ever touched a URL, shell history, or chat log
  unencrypted — cheap insurance on a disposable dev instance.
- Consider whether `ados_executive_copilot` should have its ServiceNow
  tools removed now that `ados_itsm_agent` owns that job — it's currently
  still carrying create/delete tools for incidents, cases, tickets,
  requests, assets, and users it no longer needs to.
