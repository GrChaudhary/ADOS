# Connecting ADOS to a real ServiceNow instance

This is Stage 4 of [PRODUCTIZATION.md](PRODUCTIZATION.md) — the step that
turns ADOS from a system that decides things into a system that *does*
things.

[In plain terms: right now, when the AI decides to disable someone's
account, a human approves it, and it gets written to the audit log — nothing
actually happens anywhere. The action is logged as "pretend I did this."
This document is how you make one of those actions real.]

## Why this matters more than the next feature

Everything impressive about ADOS — risk tiering, human approval, the
tamper-evident audit trail, the circuit breaker that stops runaway
automation — is machinery for supervising actions. Today it supervises
simulations. `ConsoleConnector` accepts every capability in the system and
returns `"[console] simulated stop_payroll"`.

One real ticket in one real system is worth more than a fifth domain pod.

## Get an instance (free, ~5 minutes, no procurement)

ServiceNow gives away full Personal Developer Instances (PDIs).

1. Sign up at <https://developer.servicenow.com> and request an instance.
2. You'll get a URL like `https://dev123456.service-now.com`, an `admin`
   username, and a generated password.
3. PDIs hibernate after a few days of no use and are reclaimed after about
   ten. Fine for a pilot; don't put anything you care about in one.

Then point ADOS at it:

```bash
# .env — never commit this file, it's gitignored
SERVICENOW_INSTANCE_URL=https://dev123456.service-now.com
SERVICENOW_USERNAME=admin
SERVICENOW_PASSWORD=your-generated-password
```

No ServiceNow-side configuration is needed. The tables ADOS writes to
(`incident`, `change_request`) exist on a bare instance.

## Prove it works

```bash
./.venv/bin/python scripts/servicenow_smoke.py
```

This drives the **real** path — `IntegrationHub` → policy engine →
`ServiceNowConnector` → Table API — creates a ticket, reads it back by
`sys_id`, and prints a URL you can open in a browser. It deliberately sends
the exact payload the MOA produces, not a hand-tuned one.

A pass means the connector genuinely works. Anything else is specific:

| Output | What it means |
|---|---|
| `Went to connector 'console', not servicenow` | The three env vars aren't visible to this process. Nothing real happened. |
| `ServiceNow returned 401` | Wrong username/password. |
| `ServiceNow returned 403` | The account lacks write access to that table. |
| `short_description is EMPTY` | The field-mapping regression is back — see below. |
| `httpx.ConnectError` | Instance URL wrong, or the PDI is hibernating (log in via the browser to wake it). |

The smoke script creates **real records**. Delete them when you're done, and
never point it at an instance anyone depends on.

## What gets created

| ADOS action | ServiceNow table | Why |
|---|---|---|
| `revoke_building_access` | `change_request` | A deliberate, approved change to a system of record. |
| `disable_it_access` | `change_request` | Same. |
| `stop_payroll` | `change_request` | Same. |
| `notify_manager` | *(none — stays simulated)* | It's a notification, not a ticket, and no mail connector exists. Routing it here to make it "look real" would dress up a gap. |
| ITSM agent's `create_incident` | `incident` | Already worked; unchanged. |

`change_request` is a simplification, and a deliberate one: it's the correct
ITIL vehicle for an approved change, and it exists on a bare PDI with no
setup. A production deployment with a configured Service Catalog would more
likely route offboarding to `sc_req_item`/`sc_task` off an "Employee
Offboarding" catalog item.

## The bug this closed

Worth knowing about, because it's the kind that hides.

`ServiceNowConnector` used to POST `CapabilityCall.input` straight to the
Table API. That works for the ITSM agent, which sends real ServiceNow field
names (`short_description`, `description`). The MOA doesn't — it sends
`{"employee_name": "Jane Doe", "action": "stop_payroll"}`, and none of those
are ServiceNow columns.

**ServiceNow ignores unknown fields and still returns 201.** So an
offboarding would have created a blank ticket, gotten a success back, and
written SUCCEEDED into the tamper-evident audit trail. A silent wrong-success
is worse than a failure — the audit trail would have been confidently wrong.

The translation now lives in
[`integrations/connectors/servicenow_fields.py`](../integrations/connectors/servicenow_fields.py),
explicitly per capability, and the connector never posts raw input again.
`tests/test_servicenow_fields.py` asserts on the actual bytes sent, not just
the status code, so the regression can't come back quietly.

## Then: the full workflow

Once the smoke test passes, the real milestone is an offboarding end to end:

1. `POST /moa/tasks` — "offboard Jane Doe"
2. The MOA plans the steps itself and proposes them one at a time.
3. Low-risk steps auto-execute; `disable_it_access` pauses for a manager;
   `stop_payroll` pauses for an executive.
4. Approve them, and **real change requests appear in ServiceNow**.
5. The audit trail records what happened, tied to who approved it.

That is the first time this system does something a business would pay for.
