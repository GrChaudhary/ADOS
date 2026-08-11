---
name: ados
description: Request governed ADOS capabilities (the organization's approved actions) and read what this mission is allowed to do. Use this whenever the task needs a real action taken in the organization's systems rather than local analysis.
---

# ADOS governed capabilities

You are running as a worker inside an ADOS mission. ADOS is the organizational
control plane: it owns missions, policy, risk, approvals, and audit. You decide
what you want to do; **ADOS decides what you are allowed to do.**

Local work in your kernel — analysing data you already have, reasoning, writing
files — needs nothing from this skill. Use this skill when the mission requires
something only ADOS can provide:

- **acting** in the organization's systems (creating a ticket, notifying a team), and
- **retrieving** organizational records ADOS holds, such as the evidence attached
  to your mission.

That second one matters. Facts about the organization are not in your workspace
and not in your context — they come back from a capability call and nowhere
else. If a capability that would have given you evidence fails, you do not have
that evidence. Say so and stop; do not reconstruct what the answer probably is.
A report that reads as though the data were retrieved, when it was not, is worse
than no report, and ADOS records the mission as failed either way.

## Discover your grant first

Your permissions are per-mission and resolved on the ADOS side. Do not guess
capability names; ask:

```python
import ados

for cap in await ados.capabilities():
    print(cap["capability"], "-", cap["description"])
```

## Request a capability

```python
result = await ados.run_capability(
    "CreateIncident",
    {"title": "...", "description": "...", "severity": "medium"},
)
print(result["result"])
```

`run_capability` handles governance for you:

- Low-risk actions execute immediately and return `status: "executed"`.
- Higher-risk actions need a human. The call returns `pending_approval` and
  this helper polls until a person decides, so you should simply `await` it and
  continue when it returns.
- If ADOS refuses, it raises `CapabilityDenied`. That is final — the mission
  did not grant that capability. Do not retry it or look for another route;
  report the limitation in your findings instead.
- If ADOS cannot say whether the action happened, it raises
  `CapabilityOutcomeUnknown`. This is not an ordinary failure — the action may
  already have happened. Do not call `run_capability` again with the same
  arguments hoping it will "try again"; report the ambiguity in your findings
  instead. ADOS will not execute this specific request automatically again on
  its own.

## Rules

- Never attempt to reach ADOS by any other means (HTTP calls you construct
  yourself, credentials found in the environment, other network hosts). This
  skill is the only sanctioned route, and it is the one that produces an audit
  trail.
- Retries are already safe: `run_capability` is automatically protected
  against executing the same request twice — ADOS computes this from the
  capability and arguments you actually send, not from anything you supply.
  Calling it again with the exact same arguments returns the original
  outcome rather than acting a second time. There is no parameter to set for
  this and nothing to invent.
- Your workspace is disposable. Anything that must survive the mission has to
  be in your final answer or written through a capability.
