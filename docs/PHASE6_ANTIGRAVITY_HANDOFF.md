# ADOS Phase 6 — Frontend Reconciliation for MOA, Governance & Integrations (Context Prompt for Antigravity)

Paste this whole document as your starting context. It is self-contained —
you don't need anything from a prior conversation.

## Project

ADOS (Autonomous Defect & Orchestration System) is being generalized from
a manufacturing-incident-response system into a domain-agnostic
multi-agent orchestration platform. Repo root:
`/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS`
(git repo — run `git log --oneline -5` and `git status` before editing;
there is a large batch of **already-staged, uncommitted work** in the
tree from the current session, both backend (Kafka, MOA) and frontend
(the Jarvis workspace, governance/integrations panels) — don't discard
or `git checkout --` anything without checking `git status` first).

## What just landed on the backend (not your job, already done — read only)

Three real, tested, backend-only milestones landed today in
`orchestrate/`, `backend/app/`, and `contracts/`:

1. **Real Apache Kafka event bus** (`backend/app/eventbus/kafka_bus.py`) —
   an opt-in `EVENT_BUS_BACKEND=kafka` alongside the existing
   `memory`/`redis` backends. Default stays `memory`. Nothing here
   changes any frontend contract — the event shape frontend already
   consumes (`EventEnvelope` in `lib/api.ts`) is identical regardless of
   backend.
2. **A real SSE bug, found and fixed** — `GET /events/stream` used to
   never deliver a live event past its initial `": ping"` line, on any
   backend, because the route's own polling loop was accidentally
   destroying its own subscription every ~0.5s of silence. This is now
   fixed and regression-tested (`tests/test_events_stream_router.py`).
   **Practical effect for you**: `openIncidentEventStream()` in
   `lib/api.ts` (used for live incident event feeds, e.g. Mission
   Control / incident detail pages) should now genuinely receive live
   events where it may previously have silently gone quiet after the
   first ping. If any existing frontend code has a workaround for "SSE
   seems to stop working" (a manual reconnect-on-timer, polling
   fallback, etc.), it's worth re-testing whether that workaround is
   still needed — but do not remove such a workaround speculatively,
   only if you've verified live that the plain SSE path now works.
3. **MOA (Main Orchestrating Agent) — HR domain vertical slice, new** —
   this is the big one and is detailed fully in the next section, since
   a good chunk of your job is reconciling frontend code that already
   tried to integrate with it.

## MOA — what it actually is and how it actually behaves

`orchestrate/moa/` is a new ReAct-style dynamic planner: given a natural
instruction like "Offboard Priya Nair, last day is Friday," an LLM
decides **one action at a time** — never a pre-baked plan — choosing from
4 HR actions, each individually submitted for a governance verdict before
it executes:

| Action key | What it does | Governance tier | Why |
|---|---|---|---|
| `revoke_building_access` | Revoke badge access | **Tier 0 — Autonomous** | low risk, $0 exposure |
| `notify_manager` | Notify the employee's manager | **Tier 0 — Autonomous** | low risk, $0 exposure |
| `disable_it_access` | Disable email/VPN/tools access | **Tier 1 — Approval Required** | $40k exposure band |
| `stop_payroll` | Stop final paycheck processing | **Tier 2 — Executive Approval** | "critical" risk class, unconditional |

Verified live against the real NEMOTRON LLM (not just mocked tests): the
model, with zero scripting, chose a real 4-step sequence and organically
hit all three tiers — two actions auto-executed, two paused for approval.

**API surface** (`backend/app/routers/moa.py`):

- `POST /moa/tasks` — body `{"domain": "hr", "employee_name": string,
  "instruction": string}`. `domain` must currently be `"hr"` (400
  otherwise — only one domain pod exists so far). Response is **either**:
  - a terminal result: `{"status": "ok" | "error" | "not_configured" | "max_iterations_exceeded", "answer": string | null, "toolsCalled": string[], "modelUsed": string | null}`
  - **or**, if the very next action needs a human: `{"status": "pending_approval", "taskId": string, "proposedAction": {"action_key": string, "capability": string, "summary": string, "estimated_cost_usd": number, "policy_tier": 0 | 1 | 2}}`
- `POST /moa/tasks/{taskId}/approve` and `POST /moa/tasks/{taskId}/reject`
  — no request body. Response shape:
  - if the task now finishes: `{"status": "ok" | "error" | ..., "answer": ..., "toolsCalled": [...], "approvalDecision": "approved" | "rejected"}`
  - **if the task pauses AGAIN on a second/third action in the same
    task** (this is common — a real offboarding task usually pauses
    2-3 times): `{"status": "pending_approval", "taskId": string,
    "proposedAction": {...same shape as above...}}` — this used to be
    missing `proposedAction` on the re-pause response (an earlier version
    of this doc flagged it as a known gap); it's fixed now, verified live
    with a real multi-pause task, so the client can render the next
    approval card directly from the approve/reject response without a
    second call.
- **RBAC, enforced server-side, not just client-side decoration**: a
  `MANAGER`-role user gets a 403 trying to approve **or** reject a
  Tier-2 (`stop_payroll`) action — only `EXECUTIVE`/`ADMIN` can. A
  user's `approvalLimitUsd` is also checked against the action's
  `estimated_cost_usd`. Any UI that lets a user attempt an approval they
  aren't authorized for should show the real 403 error message from the
  backend, not swallow it.
- Tasks are **not** currently published to the event bus — MOA activity
  will not appear in the existing `/events` or `/events/stream` feeds
  (Mission Control, the incident replay view, etc.). Don't build a
  feature that assumes MOA actions show up there; that would require a
  backend change that hasn't been scoped yet.

## Your job — reconcile the existing frontend against the real backend

A substantial chunk of frontend work already exists for this
(`frontend-next/src/components/jarvis/LangGraphAgentWorkspace.tsx`,
`app/jarvis/page.tsx`, plus governance/integrations panels) — well
structured, good visual design, but built slightly ahead of/out of sync
with the real backend contracts above. This is **reconciliation and
completion work**, not a rebuild. Work through these in order; 1-3 are
outright bugs (the feature is currently non-functional), 4 is a
visibility gap, 5-6 are judgment calls to make (not just fix).

### 1. Fix the ITSM agent and Executive Copilot request field name (breaks every call today)

`lib/api.ts`'s `askITSMAgent` and `askExecutiveCopilotLangGraph` send the
wrong JSON field name. The real backend (`backend/app/routers/
langgraph_agents.py`'s shared `AgentAskRequest` model) only accepts
`{"query": "..."}` for **both** endpoints.

```ts
// lib/api.ts — current (broken, 422 from the backend every time):
askExecutiveCopilotLangGraph: (question: string) =>
  apiFetch<ExecutiveCopilotAskResponse>("/agents/executive-copilot/ask", { method: "POST", body: JSON.stringify({ question }) }),
askITSMAgent: (prompt: string) =>
  apiFetch<ITSMAskResponse>("/agents/itsm/ask", { method: "POST", body: JSON.stringify({ prompt }) }),

// fix: both must send { query: ... }
askExecutiveCopilotLangGraph: (query: string) =>
  apiFetch<ExecutiveCopilotAskResponse>("/agents/executive-copilot/ask", { method: "POST", body: JSON.stringify({ query }) }),
askITSMAgent: (query: string) =>
  apiFetch<ITSMAskResponse>("/agents/itsm/ask", { method: "POST", body: JSON.stringify({ query }) }),
```
Update the call sites in `LangGraphAgentWorkspace.tsx` (variable names
`execPrompt`/`itsmPrompt` can stay as-is client-side, only the wire field
changes).

### 2. Fix the ITSM pending-approval response shape mismatch

The real backend returns `status: "pending_approval"` (not
`"paused_for_approval"`) and the field is `proposedIncident` (not
`proposedAction`) — see the exact backend code in the MOA section above
(same router file, `ask_itsm_agent`). Today, `LangGraphAgentWorkspace.tsx`'s
"Ticket Creation Paused for Approval" card checks
`itsmResult.status === "paused_for_approval"`, which never matches the
real value, so **that card can never render** even when the backend is
genuinely waiting for approval — the user gets no indication anything is
pending.

Fix `ITSMAskResponse` in `lib/api.ts`:
```ts
export interface ITSMAskResponse {
  status: "ok" | "pending_approval" | "not_configured" | "error" | "max_iterations_exceeded" | string;
  requestId?: string;
  answer?: string | null;
  toolsCalled?: string[];
  modelUsed?: string | null;
  proposedIncident?: { short_description: string; description: string } | null;
  approvalDecision?: string;
}
```
And the JSX condition/fields in `LangGraphAgentWorkspace.tsx`'s ITSM tab
accordingly (`proposedIncident.short_description`/`.description`, not a
`capability`/`input` shape — the ITSM proposal is a ServiceNow ticket
draft, not a `CapabilityCall`).

### 3. Stop discarding the real approve/reject response for ITSM

`itsmApproveMutation`'s `onSuccess` currently **ignores the actual API
response** and hardcodes a fake message:
```ts
onSuccess: () => {
  if (itsmResult) setItsmResult({ ...itsmResult, status: "completed", answer: "Action approved and executed via ServiceNow connector." });
},
```
The real response already has everything needed (`status`, `answer`,
`toolsCalled`, `approvalDecision`) — use it, the same way
`moaApproveMutation`'s `onSuccess: (data) => setMoaResult(data)` already
correctly does for MOA:
```ts
onSuccess: (data) => setItsmResult(data),
```
Do the same for `itsmRejectMutation`. This also means whatever connector
actually fulfilled the ticket (real ServiceNow if configured, `console`
fallback otherwise per `integrations/connectors/console.py`) is reflected
honestly instead of an unconditional "via ServiceNow connector" claim
that isn't always true.

### 4. Wire up navigation — the new work is currently unreachable

`components/design-system/Sidebar.tsx`'s `NAV_ITEMS` only has 7 entries
(Executive, Twin Room, Incidents, Decisions, Knowledge, Memory,
Settings). Confirmed via a repo-wide search: **`/jarvis` (the whole MOA/
ITSM/Executive-Copilot workspace), `/governance`, and `/integrations`
have zero in-app links anywhere** — they only exist if someone types the
URL directly. Add nav entries for at least these three (suggested,
adjust icons/labels to match house style):
```ts
{ href: "/jarvis", icon: "🧠", label: "Jarvis / MOA" },
{ href: "/governance", icon: "⚖️", label: "Governance" },
{ href: "/integrations", icon: "🔌", label: "Integrations" },
```
`/admin`, `/agents/network`, `/novus`, `/novus-studio`, `/policy-studio`,
`/replay` are also unlinked from anywhere — check with the user whether
those are deliberately hidden/easter-egg routes before adding them to
primary nav; don't assume.

### 5. Governance page: surface the new HR capability risk classes (data already there, just not rendered)

`GET /governance/policies` (already called by `governance/page.tsx`)
already returns a `capabilityRiskClass: Record<string, string>` field —
confirmed live, it now includes the 4 new HR capabilities automatically
(`RevokeBuildingAccess: "low"`, `DisableITAccess: "medium"`,
`StopPayroll: "high"`, `NotifyManager: "low"`, alongside the original 10
manufacturing/ITSM capabilities) with **zero API changes needed**. But
`governance/page.tsx` never renders this field anywhere today — only
`financialExposureBands`, `rbacApprovalRules`, and `itsmLiveWriteGate`
are shown. Add a simple table/list section rendering
`policies.capabilityRiskClass` (capability name → risk class badge) so
the new HR capabilities' governance classification is actually visible,
not just computed silently server-side.

### 6. Two panels' backend endpoints — now built AND wired up (update since this doc was first written)

The endpoints this section originally flagged as missing have since been
built for real (not stubbed) and are covered by 14 new backend tests
(`backend/tests/test_capabilities.py`, `backend/tests/test_governance.py`)
plus a live smoke test against the real app. Both `CircuitBreakerCard`
(`app/governance/page.tsx`) and `CapabilityManifestRegistryPanel`
(`app/integrations/page.tsx`) — which had, in between, been rewritten as
purely static/illustrative cards (hardcoded text like "Max 3–5
Auto-Approvals", no `useQuery` at all) — are now fully wired to the real
endpoints via `useQuery`/`useMutation`, same pattern as `statusQuery` in
`integrations/page.tsx` and `policiesQuery` in `governance/page.tsx`.
Verified via `npx tsc --noEmit`, `npm run build`, and a live curl round
trip (proposed a manifest, drove an MOA task to trip the breaker OPEN,
confirmed both endpoints reflect it, then cleaned the test data back out).
Nothing left to do here unless you're changing behavior:

- `CircuitBreakerCard` now shows live `state`/`auto_approved_count`/
  `threshold`/`active_tasks`/`open_task_ids`, polls every 5s, and has a
  role-gated (non-auditor) "Clear after review" button that only appears
  when `state === "OPEN"`.
- `CapabilityManifestRegistryPanel` now lists real manifests (polls every
  10s) with status/risk badges, sandbox evidence rendered as the plain
  string it actually is (`m.sandbox_evidence ?? "not yet tested"` — never
  `.passed_checks`/`.total_checks`, there is no such object), and
  role-gated (admin/executive) Activate/Resume/Hot-Disable buttons that
  only appear for the status transitions the backend actually allows.
- The literal-class-name gotcha bit the previous static version of this
  panel for real: its `STAGES` array did `` `bg-${color}/20` `` with
  `color: "red"`, but the real design token is `status-red` (see
  `globals.css`), not bare `red` — Tailwind's scanner never generated
  that class, so the "Hot Disabled" badge silently rendered unstyled.
  Fixed by switching to static `Record<status, string>` lookup objects
  (`STATUS_BADGE_CLASS`/`RISK_BADGE_CLASS`) with full literal class
  strings, per this file's own documented convention below.
- There is still no admin-facing "propose a new capability" endpoint —
  that's intentional (§8.3: "the agent proposes; it never self-approves,"
  proposals come from an onboarding agent, not an admin form), so the
  manifest list will legitimately stay empty until something actually
  calls `.propose()`. The panel's empty state says this explicitly. Don't
  add a propose button/endpoint as part of this work — that's the
  separate, still-unbuilt "capability onboarding meta-agent" milestone
  (vision doc §8), out of scope here.

## Conventions already established — reuse, don't reinvent

- **Design tokens / Tailwind**: same as prior phases — `globals.css`'s
  CSS custom properties via Tailwind v4's `@theme inline`, no
  `tailwind.config.ts`. Remember the literal-class-name gotcha: Tailwind
  only generates CSS for class names that appear as complete literal
  strings in source, `` className={`text-${color}`} `` will not work —
  use a static lookup object (see `KpiCard.tsx`'s `ACCENT_TEXT_CLASS`).
- **API client**: everything goes through the single exported `api`
  object in `lib/api.ts` — add functions there, don't create a second
  client. Every type in that file is meant to be written **literally as
  it appears on the wire** per endpoint (the backend's JSON casing is
  genuinely inconsistent field-by-field — some pydantic models alias to
  camelCase, some fields on those same models don't, some hand-built
  dict endpoints are snake_case throughout). When in doubt, read the
  actual FastAPI router and its pydantic model before typing a new
  field — don't assume uniform casing. This file's own header comment
  says the same thing; it's still true.
- **Auth**: `getToken()`/`setToken()`, `localStorage` key
  `ados_service_token`, already wired everywhere via `apiFetch()`. RBAC
  roles are `manager | executive | admin | auditor`
  (`backend/app/rbac.py`) — `useCurrentUser.ts`/`getStoredUser()` gives
  you the logged-in user's role and `approvalLimitUsd` if you need to
  pre-emptively grey out an action the backend would 403 anyway (nice
  UX, but the backend check is the real enforcement — don't rely on the
  frontend gate alone, and don't remove/weaken the backend's own check).
- **SSE**: `openIncidentEventStream()` in `lib/api.ts` — now genuinely
  reliable past the initial ping (see the SSE bug fix above). Connects
  directly to the backend origin with a `?token=` query param, not
  through the Next.js rewrite proxy (`EventSource` can't set headers or
  reliably traverse a rewrite for a long-lived stream).
- **Shared shell**: `AppShell.tsx`/`Sidebar.tsx`/`HeaderTelemetryBar.tsx`/
  `FooterStatusBar.tsx` wrap every route via root `layout.tsx` — pages
  just return their body content.

## Do not touch

Any `.py` file, anywhere in the repo — everything in this handoff is
frontend-only (`frontend-next/`). If a real fix requires a backend
change, write it down and flag it back rather than editing Python (the
MOA pause-again gap and the two missing endpoint clusters both flagged
this way in earlier drafts of this doc — see git history if you want the
original framing — and both got fixed backend-side rather than worked
around in the frontend). Also leave alone:
`frontend-next/src/app/digital-twin/*` and
`frontend-next/src/app/incidents/[incidentId]/*` (a different owner's
screens per the prior phase's split), `frontend-next/src/app/layout.tsx`,
`AppShell.tsx` and its Sidebar/Header/Footer siblings' *structure*
(adding a nav item to `Sidebar.tsx`'s `NAV_ITEMS` array is explicitly
fine and requested above — don't restructure the component itself),
`frontend-next/src/app/globals.css`'s token values (adding new
component-scoped classes is fine), `frontend/` (the old plain-JS
dashboards, unrelated, kept as-is).

## Verification

```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/frontend-next"
npm run build   # must have zero TypeScript errors
npm run dev     # :3000
```

Backend, for live testing against real data (not mocks):
```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
docker compose up -d postgres kafka   # both must be running
set -a && source .env && set +a       # picks up the real NEMOTRON key so MOA/ITSM/Copilot actually respond instead of "not_configured"
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```
Demo account passwords are randomly generated on first boot and only
printed once to that first boot's console — if you don't have them, mint
a JWT directly instead of logging in through the UI (same trick used to
verify this backend earlier today, no DB dependency):
```bash
./.venv/bin/python3 -c "
from backend.app.rbac import Role, User, create_access_token
u = User(user_id='dev', username='dev', display_name='Dev', role=Role.ADMIN, approval_limit_usd=1_000_000_000.0)
print(create_access_token(u))
"
```
Paste the token into `HeaderTelemetryBar`'s token box (or
`localStorage.setItem('ados_service_token', '<token>')` in the browser
console) to authenticate the frontend session directly.

Confirm, with real (not scripted) LLM calls where possible:
1. `/jarvis` is reachable from the sidebar, and all 3 tabs (MOA, ITSM,
   Executive Copilot) submit successfully (no 422s) and render real
   responses.
2. Trigger a real MOA offboarding task and drive it through at least one
   approve — the "Action Held for Governance Approval" card must show
   real `action_key`/`summary`/`estimated_cost_usd`/`policy_tier`
   values pulled from the actual response, not placeholders.
3. Trigger a real ITSM "create a ticket" prompt — the pending-approval
   card must now actually appear (it couldn't before, see item 2 above),
   and approving it must show the real connector/answer, not the old
   hardcoded string.
4. `/governance` shows the new HR capabilities somewhere in the risk
   class display. The circuit breaker panel is now backed by a real
   endpoint — start a real MOA task, confirm it flips to `OPEN` once
   enough autonomous actions have auto-approved in a row (default
   threshold 4; `revoke_building_access`/`notify_manager` are the two
   autonomous-tier actions, so scripting/triggering several of those
   consecutively is the fastest way to see it live), and confirm "Reset
   Breaker" actually closes it.
5. `/integrations`'s capability manifest panel loads real data (an empty
   list is correct and expected — nothing has been proposed yet, see
   item 6 above; `npm run build` is already clean, this is just
   confirming it stays that way as you keep working in this area).

When done, commit your changes with a clear message.
