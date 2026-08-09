# Current Runtime State — Prime Agent Integration

Produced 2026-08-09 by inspection and runtime execution of the code in this
repository. No implementation code was modified to produce this document.

Method: every claim below is backed by either a file:line reference or a
command that was actually run. Where a claim in
`09-existing-prime-agent-onboarding.md` or `CLAUDE.md` disagrees with the
repository, the repository is treated as the source of truth, per that
document's own §7.

---

## Headline finding

**There is no Prime Agent runtime, and there is no code capable of reaching
one.** `PrimeAgentClient.execute_rlm_task()` returns a hardcoded dictionary on
both of its branches. The branch guarded by `is_configured()` — the one the
docstring calls "the live harness" — is also fabricated.

This is not a "simulation mode for tests with a real path alongside it." It is
a simulation with two different fake payloads.

[In plain terms: the Prime Agent node exists in the agent list, has a risk
rating, and passes its tests — but nothing in ADOS has ever contacted Prime
Intellect, and no code in this repository could. What looks like an
integration is a placeholder that returns believable-looking text.]

### Evidence

`knowledge/prime_agent_client.py` imports exactly `logging`, `os`, `uuid`,
`typing`. Checked programmatically for any means of leaving the process:

```text
module references 'httpx'      : False
module references 'requests'   : False
module references 'aiohttp'    : False
module references 'subprocess' : False
module references 'socket'     : False
module references 'urllib'     : False
module references 'websocket'  : False
module references 'import prime': False
```

Executed with a deliberately invalid key and an unroutable host:

```text
PRIME_AGENT_API_KEY = "obviously-not-a-real-key-12345"
PRIME_AGENT_HOST    = "https://this-host-does-not-exist.invalid"

is_configured()  -> True
status returned  -> success
harness claimed  -> PrimeIntellect Continual Harness v1.0
output           -> Executed RLM recursive task: delete all production data
trace lines      -> 5
```

A junk credential pointed at a non-existent host returns `success` with a
five-line execution trace. Nothing was contacted.

`self.api_key` (line 19) and `self.host` (line 20) are assigned and never read
again anywhere in the file.

### The specific claims that are wrong

| Claim | Source | Reality |
|---|---|---|
| "If `PRIME_AGENT_API_KEY` is configured, dispatches to the live harness" | `prime_agent_client.py:35` docstring | Returns a literal dict (lines 47–62). No dispatch exists. |
| "`execute_rlm_task()` execution facade" | `CLAUDE.md` §Already completed | It is not a facade over anything; there is no thing behind it. |
| "dynamic MOA actions can select `RunPrimeRLMAgent` for `it`, `devops`, `general`" | `CLAUDE.md`, `09-…md` §4 | No MOA action references it; no `devops` domain exists anywhere in the repo. See "MOA integration" below. |

Claims that **are** accurate: the capability enum, the risk classification,
both registry entries, the reasoning node with the `🧬` icon, and the test
counts. `09-existing-prime-agent-onboarding.md` §6 is also honest — it
correctly disclaims persistence, sessions, events, and resume. The overstatement
is concentrated in the client docstring and the `CLAUDE.md` summary.

---

## Runtime topology

```text
Actual, today:

  backend/tests/test_prime_agent.py
        |
        v
  PrimeAgentClient.execute_rlm_task()   <-- returns a literal dict
        |
        v
  (nothing)

  Nothing else in the repository calls it.
```

There is no process, container, subprocess, socket, HTTP client, SDK, or
vendored source for Prime Agent. `find` for any `*prime*` path outside
`.venv/` and `node_modules/` returns exactly two files: the client and its
test. `requirements.txt` and `package.json` declare no Prime dependency.

The separate registry surface is real but decorative:

```text
  GET /agents-registry  ->  200, 10 agents, includes id=prime-rlm-agent
        |
        v
  frontend-next/src/lib/agents.ts  ->  renders a Reasoning node
```

That endpoint returns metadata only. It is not an execution path.

## Production execution path

```text
There is none.
```

`execute_rlm_task` has **zero callers** outside its own module and its test
file:

```bash
grep -rn "execute_rlm_task\|prime_agent_client\|PrimeAgentClient" --include="*.py" . \
  | grep -v ".venv\|knowledge/prime_agent_client.py\|backend/tests/test_prime_agent.py"
# (no output)
```

Even if something wanted to call it through the normal capability path, it
could not: `Capability.RUN_PRIME_RLM_AGENT` is **not routed to any connector**.
It appears in exactly three places — the enum
(`contracts/capabilities.py:47`), the risk map
(`orchestrate/governance.py:58`), and the tests. No connector under
`integrations/` declares it, so `IntegrationHub` has nothing to dispatch it to.

## Test execution path

```text
backend/tests/test_prime_agent.py::test_prime_agent_client_simulation
  -> prime_agent_client.execute_rlm_task(...)
  -> unconfigured branch (lines 65-84)
  -> asserts status == "success", agent == "prime-rlm-agent",
     and that a trace array is non-empty
```

Verified: `24 passed` for
`test_prime_agent.py test_agents_registry.py test_capabilities.py`, matching
the claimed baseline exactly. Frontend `tsc --noEmit` exits 0.

**What the tests actually prove:** that the hardcoded dictionary contains the
keys the test expects. `test_prime_agent_client_simulation` asserts against
literals defined ten lines away in the same repository. It would pass
identically if Prime Agent did not exist — which, as an integration, it
currently does not. This is the same shape as the previously-recorded case
where a green suite hid a fully dead feature.

`test_prime_agent_client_configured_property` is a genuine test of
`is_configured()`, and is fine.

## Persistence

| Question | Answer |
|---|---|
| What survives process restart? | Nothing. |
| Where does state live? | Nowhere. No table, no file, no checkpoint. |
| Does Prime Agent own state? | No Prime Agent process exists. |
| Does ADOS own state? | No — nothing is written for this capability. |
| What is lost on restart? | Nothing, because nothing is retained. |

`task_id` is generated per call (`prime_agent_client.py:38`) and returned to
the caller, but it is never stored, indexed, or usable to look anything up. It
is a label on a response, not a handle.

Note the contrast with what ADOS *does* have as of 2026-08-09: MOA and ITSM
approvals are durable via `db/checkpointer.py` and `moa_task_breakers`. The
durable-state machinery a persistent runtime would need already exists in this
codebase and is proven across process boundaries — it simply has no connection
to Prime Agent.

## Session model

| Primitive | Supported |
|---|---|
| create | No |
| start | No |
| pause | No |
| resume | No |
| cancel | No |
| status | No |
| health | No |
| events | No |

`execute_rlm_task` is a single `async def` that awaits nothing and returns
once. There is no session object, no identifier that outlives the call, and no
way to observe or interrupt anything mid-flight.

## Prime Agent capabilities actually wired

"Available in Prime Agent" is left as **Unverified** throughout: this
inspection covers the ADOS repository and its runtime. No Prime Agent
version, commit, endpoint, or SDK is referenced anywhere in this repository,
so there is nothing here from which to determine what the upstream product
offers. Determining that requires going to the upstream project directly, and
per `09-…md` §7 it must not be inferred from documentation alone.

| Capability | Available in Prime Agent | Wired into ADOS | Evidence |
|---|---|---|---|
| RLM/context execution | Unverified | **No — simulated** | Both branches return literals; junk key returns `success` |
| persistent session | Unverified | No | No session primitives exist |
| subagents | Unverified | No | No reference in repo |
| messaging | Unverified | No | No reference in repo |
| skills | Unverified | No | No reference in repo |
| goals | Unverified | No | No reference in repo |
| heartbeat | Unverified | No | No reference in repo |
| schedules | Unverified | No | No reference in repo |
| continual refinement | Unverified | No | `harnessRefinements` is two hardcoded strings (lines 80–83) |
| daemon/background execution | Unverified | No | No process is ever started |

## Governance boundary

**Where `RunPrimeRLMAgent` is checked:** only in
`orchestrate/governance.py:58`, which classifies it `"medium"` risk.
`assign_policy_tier` then combines that with confidence and estimated cost.

**Where capability calls are authorized:** the standard path
(`IntegrationHub` → policy tier → approval) is never reached, because no
connector handles the capability and nothing constructs a `CapabilityCall`
for it.

**Can Prime Agent call ADOS capabilities directly?** Not applicable — no Prime
Agent process exists. Correspondingly, no mediation layer exists either, so
this question must be answered before any real runtime is introduced.

**Are external actions mediated?** There are no external actions.

**Where are audit events recorded?** Nowhere for this capability. A call to
`execute_rlm_task` writes one `logger.info` line
(`prime_agent_client.py:39`) and produces no audit-trail entry, no event on
the bus, and no database row.

### A contradiction worth resolving before Stage 3

The registry advertises the Prime node as **Tier 1 (Engineer Approval)**
(`agents_registry.py`, `agents.ts`). The policy engine disagrees:

```text
confidence=0.95  cost=$    1,200  -> AUTONOMOUS
confidence=0.95  cost=$        0  -> AUTONOMOUS
confidence=0.85  cost=$   30,000  -> APPROVAL_REQUIRED
```

`targetTier` is display-only metadata — grepping for reads of it finds only
registry definitions and the UI detail panel; no policy code consults it. So
the UI would tell an operator a human must approve, while
`assign_policy_tier` would return Tier 0 and let it run unattended.

This matters specifically for this capability. An RLM coding agent has no
natural dollar cost, so `estimated_cost_usd` defaults toward 0 — landing it in
the autonomous band. The capability is described in its own registry entry as
executing code in an IPython kernel sandbox and auto-fixing bugs. A "medium"
classification puts arbitrary code execution in the same band as
`GRANT_JIRA_ACCESS` and `UPDATE_MES`.

Today this is harmless, because the capability cannot execute. It stops being
harmless the moment a real runtime is connected, and the risk class is the
thing to fix *before* that, not after.

## Key gaps

Evidence-backed, ordered by what blocks the next milestone:

1. **No runtime exists.** Nothing to make persistent, resumable, or
   observable yet. Every item in `CLAUDE.md`'s "first implementation
   milestone" depends on this.
2. **No capability→connector route.** `RUN_PRIME_RLM_AGENT` cannot be
   dispatched by `IntegrationHub`, so even a working client would be
   unreachable through the governed path.
3. **No MOA reachability.** No domain action set references the capability,
   no `devops` domain exists, and no onboarded manifest supplies it
   (`select … from capability_manifests where capability_id ilike '%prime%'`
   → 0 rows). The MOA API's accepted domains are `hr, it, finance,
   manufacturing, mfg, cross-domain, all, multi`.
4. **The "live" branch is fabricated.** It must be deleted or replaced
   outright, not extended — leaving it in place means a future misconfiguration
   silently returns fake successes instead of failing.
5. **Advertised tier contradicts enforced tier**, and the risk class is likely
   wrong for arbitrary code execution (see above).
6. **No audit trail.** Governed execution requires an audit record; none is
   written.
7. **`PRIME_AGENT_API_KEY` is undocumented.** Absent from `.env.example`,
   `backend/app/config.py`, and `docker-compose.yml`. It is also read via
   `os.environ` directly rather than through `settings`, which works only
   because `config.py:25` calls `load_dotenv` — an implicit dependency on an
   unrelated module having been imported first.
8. **None of this is committed.** `knowledge/prime_agent_client.py` and
   `backend/tests/test_prime_agent.py` are untracked; the four edited files are
   unstaged. The integration exists only in the working tree.

## Recommended next implementation slice

The smallest slice that converts this from a placeholder into something real,
without starting on sessions, subagents, or schedules:

**Make one genuine round trip to Prime Agent, through the governed path, and
prove it fails correctly when unreachable.**

1. Establish what the upstream runtime actually is — package, endpoint, or
   process — and pin it in `requirements.txt`. This is the missing input that
   blocks every other decision; nothing in this repository answers it.
2. Delete the fabricated `is_configured()` branch. Replace it with a real
   call. When unconfigured, raise or return an explicit `not_configured`
   status — never a synthetic `success`. This follows the convention the MOA
   already uses for unconfigured LLM providers.
3. Add a connector that declares `RUN_PRIME_RLM_AGENT` so the capability is
   reachable through `IntegrationHub` and inherits policy, approval, and audit
   for free rather than needing a parallel path.
4. Reclassify the risk. Decide deliberately whether arbitrary sandboxed code
   execution is `"medium"`, and make `targetTier` agree with
   `assign_policy_tier` — or stop displaying `targetTier` at all.
5. Write the tests against behaviour that can fail: unreachable host, invalid
   credential, timeout, and a governed call that produces an audit entry.
   Confirm each fails without the fix.

Only after a real call exists is there any point discussing sessions,
heartbeats, or resume — those are properties of a running thing, and there is
no running thing yet.

---

## Appendix — verification commands

```bash
# No callers
grep -rn "execute_rlm_task\|prime_agent_client\|PrimeAgentClient" --include="*.py" . \
  | grep -v ".venv\|knowledge/prime_agent_client.py\|backend/tests/test_prime_agent.py"

# No connector route
grep -rln "RunPrimeRLMAgent" integrations/

# No dependency, no config
grep -rn "prime" requirements.txt package.json
grep -rn "PRIME_AGENT" .env .env.example backend/app/config.py docker-compose.yml

# No onboarded manifest
docker compose exec -T postgres psql -U ados -d ados \
  -c "select capability_id from capability_manifests where capability_id ilike '%prime%';"

# Baseline preserved
./.venv/bin/pytest backend/tests/test_prime_agent.py \
  backend/tests/test_agents_registry.py backend/tests/test_capabilities.py   # 24 passed
cd frontend-next && npx tsc --noEmit                                          # exit 0
```
