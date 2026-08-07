# Keycloak Scoped-Identity Rollout — Decision & Plan

Resolves the vision doc's core-substrate item ("Decide Keycloak
scoped-identity rollout — at minimum, plan for it before Section 5.5
defense-in-depth is real"). Written 2026-08-04, same session as
[`EVENT_BUS_COMPARISON.md`](EVENT_BUS_COMPARISON.md) and
[`OPA_POLICY_SPIKE.md`](OPA_POLICY_SPIKE.md). Explicitly scoped lighter
than those two — a decision and a plan, not a spike, per the TODO's own
wording.

## What Section 5.5 actually needs, and whether it exists yet

Section 5.5's property: *"each domain agent gets its own scoped service
identity (Keycloak OAuth2 client credentials) — so, structurally, the HR
agent cannot call Finance's write endpoints at the token level,
independent of whatever the policy engine decides."* That's a claim about
**two distinct entities each needing their own credential** so a bug in
one doesn't silently reach the other's resources.

Checked whether that precondition holds today, not assumed:

- **There is currently no live service-to-service authentication in
  ADOS at all.** `backend/app/auth.py`'s own docstring says the old
  shared-secret scheme (`require_service_auth()`, `service_auth_token`
  in `config.py`) was replaced by JWT/RBAC — but grepping the whole
  codebase, `require_service_auth` isn't called anywhere anymore. The one
  remaining shared-token code path, `orchestrate/langgraph_agents/
  tools.py`'s HTTP-based copilot tools (reading `ADOS_SERVICE_TOKEN`), is
  **not what the live backend route uses** —
  `backend/app/routers/langgraph_agents.py` calls `in_process_tools()`
  instead, which reads `orchestrator.audit_trail`/`orchestrator.approvals`
  directly, no HTTP call, no token at all.
- **Everything runs in one Python process.** The backend, orchestrator,
  and all agents (the original 8, plus the 2 LangGraph agents) share one
  process and one set of in-memory/DB connections. There is exactly one
  domain today (manufacturing, soon to be named Operations) — Section
  5.5's "HR agent vs. Finance agent" scenario has no second entity to
  distinguish it from yet.

Today's JWT/RBAC (`backend/app/rbac.py`, roles: manager/executive/admin/
auditor) is real and live, but it authenticates **human users**, not
agent-to-agent or agent-to-service calls. It's a different axis from
Section 5.5, not a partial implementation of it.

## Decision

**Don't stand up Keycloak now.** This is the same verdict, and the same
underlying reason, as [`EVENT_BUS_COMPARISON.md`](EVENT_BUS_COMPARISON.md)
and the OPA spike: the
property Keycloak buys — structural isolation between two independently
credentialed identities — has no consumer while there's only one domain
and one process. Running a Keycloak instance (realm setup, client
registration, token issuance/rotation, ops burden) ahead of that would be
infrastructure with no attacker/bug surface to actually defend yet, and
this project has been deliberately consistent about not doing that
(cascade breaker, Kafka/Redpanda, OPA — three prior examples this
session).

## The plan (the part the TODO explicitly still wants, even without a build)

**Trigger**: stand up Keycloak at the same point the vision doc's own
build sequence calls for it — step 3, *"Second domain pod + first real
cross-domain workflow"* — because that's the first moment two genuinely
separate domain agents coexist and a token-level boundary between them
means something. Not before; not deferred further once that step starts.

**Shape, when that happens:**
1. One Keycloak realm for the ADOS deployment.
2. One OAuth2 client (client-credentials grant) per domain pod — e.g.
   `ados-operations-agent`, `ados-hr-agent` — not per individual agent
   class within a pod; the isolation boundary that matters is between
   domains, matching the vision's own pod-level framing, not
   agent-by-agent inside one pod.
3. Every outbound call a domain agent makes to shared platform
   infrastructure (Integration Hub, event bus, capability registry)
   carries that pod's scoped token; the receiving service validates
   token audience/scope before honoring a write — independent of, and in
   addition to, whatever `ConnectorPolicyEngine`/OPA decides at the
   policy layer (the actual "defense in depth" property — two
   independent layers, not one doing double duty).
4. Human-user JWT/RBAC (`backend/app/rbac.py`) stays exactly as-is —
   different axis, not migrated onto Keycloak as part of this. (Keycloak
   *could* also issue human-facing tokens later since it's a general
   IdP, but that's a separate, optional consolidation, not a requirement
   of Section 5.5 — flagged only, not recommended here.)

**Not planned as a spike** the way OPA was, because unlike OPA there's no
cheap, honest way to spike "structural isolation between two domain
agents" when only one domain agent exists — a spike would have to
fabricate a second, fake domain agent just to have something to isolate
from, which wouldn't tell us anything a real second domain pod won't tell
us better and for free when it actually gets built.
