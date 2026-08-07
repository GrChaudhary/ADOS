# ADOS Phase 7 — Capability Onboarding UI ("BYOC Studio") — Context Prompt for Antigravity

Paste this whole document as your starting context. It is self-contained —
you don't need anything from a prior conversation.

## Project

ADOS (Autonomous Defect & Orchestration System) is a domain-agnostic
multi-agent orchestration platform. Repo root:
`/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS`
(git repo — run `git log --oneline -10` and `git status` before editing;
there may be uncommitted work in the tree from a parallel backend session
— don't discard or `git checkout --` anything without checking `git
status` first).

Frontend stack you're working in: Next.js 16 (App Router), React 19,
TanStack React Query v5, Tailwind v4. No component library (no shadcn) —
existing pages hand-roll cards/panels with Tailwind classes directly. API
calls go through `frontend-next/src/lib/api.ts` (a hand-written client,
types declared literally per the wire shape, deliberately not normalized
— read the comment at the top of that file before adding a new
endpoint's types, it explains why). Auth token lives in `localStorage`
under `ados_service_token`, read via `getToken()` in that same file;
every authenticated fetch sends `Authorization: Bearer <token>`.

## What just landed on the backend (not your job, already done — read only)

A full "Bring Your Own Capability" onboarding pipeline: paste a GitHub
repo URL (or local path), the system inspects it, figures out whether
it's an MCP-native server or has an OpenAPI spec, walks an admin through
mapping one of its tools into a governed ADOS capability, sandbox-tests
it in a real Docker container (network-isolated), and — once activated —
that capability becomes something the MOA orchestrator can pick and
invoke, right alongside its 4 built-in HR actions. Verified live against
a real LLM with zero scripting: it organically picked a freshly onboarded
capability and executed it for real.

This is a genuinely new feature with **no existing frontend at all** —
that's your job this round. The backend has zero UI today; everything
below has only ever been driven by curl/pytest.

### Two tracks exist today (a third, "raw code", is being built separately and does not exist yet — don't build UI that assumes it)

- **`mcp_native`** — the target repo already speaks MCP (Model Context
  Protocol) via `fastmcp`. Tools are discovered by actually launching the
  server.
- **`openapi`** — the target repo ships an OpenAPI/Swagger spec. Tools
  are discovered by parsing operations out of it.

Track is normally auto-detected at Turn 1; an admin can optionally
override it with `track_hint`.

### The five-turn flow — this is the actual state machine, model your wizard on it exactly

Each turn is a real, separate governance checkpoint (per the platform's
"no self-approval, no skipping the sandbox" rules) — there is no
"submit everything at once" shortcut, and the UI shouldn't pretend there
is. A session moves through these statuses in order:

`submitted → inspected → synthesized → risk_reviewed → sandbox_tested → activated`

(or `failed` / `aborted` — see error handling below)

| # | UI step | Endpoint | Request body | On success |
|---|---|---|---|---|
| 1 | **Inspect** — admin pastes a repo URL | `POST /capability-onboarding/sessions` | `{"source_url": string, "track_hint"?: "mcp_native" \| "openapi"}` | Session created, status `inspected`, returns the full tool list discovered in the repo |
| 2 | **Select tool + assign domain** — admin picks ONE tool from the list, names it | `POST /capability-onboarding/sessions/{id}/synthesize` | `{"selected_tool_name": string, "domain": string, "capability_id": string, "version"?: string, "estimated_cost_usd"?: number, "test_base_url"?: string, "production_base_url"?: string}` | status `synthesized`. `test_base_url` is **required** if track is `openapi` (backend 400s without it) |
| 3 | **Risk proposal** — no user input, just a confirm button | `POST /capability-onboarding/sessions/{id}/risk-proposal` | `{}` | status `risk_reviewed`, returns the computed risk tier + reasoning. This is also the point a real governance manifest row is created — from here on the capability is tracked in `GET /capabilities/manifests` too |
| 4 | **Sandbox test** — admin optionally supplies sample input, clicks "run test" | `POST /capability-onboarding/sessions/{id}/sandbox-test` | `{"sample_input"?: object, "acknowledge_live_call"?: boolean}` | status `sandbox_tested` on pass. **On failure this is a 422, not a terminal state** — session stays at `risk_reviewed`, retriable with different input. `acknowledge_live_call: true` is required for the `openapi` track (it's a real HTTP call against `test_base_url`, no Docker isolation possible for an external API — the UI must make the admin explicitly tick a box, not default it true) |
| 5 | **Activate** — final human sign-off | `POST /capability-onboarding/sessions/{id}/activate` | `{}` | status `activated` — capability is now live and callable by MOA |

Read-only endpoints for a session list/history view:

- `GET /capability-onboarding/sessions` → array of full session objects, newest first
- `GET /capability-onboarding/sessions/{id}` → one session object

### Full session object shape (what every endpoint above returns wrapped in, and what the GET endpoints return directly)

```ts
type OnboardingSession = {
  id: string;
  track: "mcp_native" | "openapi" | null;
  status: "submitted" | "inspected" | "synthesized" | "risk_reviewed" | "sandbox_tested" | "activated" | "failed" | "aborted";
  source_url: string;
  domain: string | null;
  capability_id: string | null;
  selected_tool_name: string | null;
  inspection_report: InspectionReport | null;
  synthesized_manifest: SynthesizedAction | null;
  sandbox_result: SandboxResult | null;
  audit_log: { turn: number; actor: string; at: string; detail: string }[];
  created_by: string;
  created_at: string; // ISO
  updated_at: string; // ISO
  failure_reason: string | null;
};

type InspectionReport = {
  source: string;
  track: "mcp_native" | "openapi" | null;
  confidence: "high" | "inferred" | "hinted" | "none";
  local_path: string | null;
  resolved_ref: string | null; // git SHA if source was remote
  language: string | null;
  tools: DiscoveredTool[];
  warnings: string[];
  launch_command: string[] | null; // mcp_native only
  openapi_spec_path: string | null; // openapi only
};

type DiscoveredTool = {
  name: string;
  description: string;
  input_schema: Record<string, unknown>; // JSON Schema — render this to show the admin what args the tool takes
  runtime: Record<string, unknown>;
};

type SynthesizedAction = {
  key: string;
  description: string;
  capability_id: string;
  domain: string;
  version: string;
  estimated_cost_usd: number;
  track: "mcp_native" | "openapi";
  runtime: Record<string, unknown>;
};

type SandboxResult = {
  passed: boolean;
  evidence_summary: string; // human-readable, show this directly
  raw_output: string; // verbose, put behind a "show details" toggle
  duration_ms: number;
};
```

### Turn 1 response shape specifically

```ts
// POST /capability-onboarding/sessions response
{ id: string; status: string; report: InspectionReport }
```

If `report.track` is `null`, inspection couldn't classify the source —
show `report.warnings` to the admin (there'll be one explaining why) and
don't let them proceed past this screen.

### Errors the UI must handle explicitly, not just show a generic toast for

- **422 on Turn 1** — `detail` is a human-readable inspection failure
  (bad URL, unreachable repo, etc.). Session is still created server-side
  with status `failed`, but there's nothing more to do with it — treat it
  as terminal, offer "try again" (new session).
- **400 on Turn 2** — either the selected tool name doesn't match
  anything in the inspection report, or (`openapi` track) `test_base_url`
  was omitted. Both are fixable inline, don't create a new session.
- **409 on any turn** — session isn't in the right status for that turn
  (e.g. double-submitting, or the browser has a stale session state).
  Refetch the session and reconcile the UI to whatever status it's
  actually at.
- **422 on Turn 4** — sandbox test failed. Show `evidence_summary`
  prominently, keep the wizard on this step, let them adjust
  `sample_input` and retry. This is expected/normal, not exceptional —
  design the empty/failure state for it, don't just red-toast it.

## Auth / RBAC — match the existing pattern exactly

Every endpoint requires authentication. The 5 mutating POSTs
additionally require role `ADMIN` or `EXECUTIVE` (backend 403s
otherwise) — the two GET endpoints are open to any authenticated role.
This is the identical gating pattern already used by
`CapabilityManifestRegistryPanel` in `src/app/integrations/page.tsx` —
read that component first, it's the closest existing analog (role check,
`useQuery`/`useMutation` wiring, auth header handling) and you should
follow its conventions rather than inventing new ones. `CircuitBreakerCard`
in `src/app/governance/page.tsx` is a second good reference for a
mutating-action-with-role-gate pattern.

Get the current user/role via whatever hook those two components already
use (check `useCurrentUser` or equivalent in `src/lib/`) — don't
re-implement role-reading from scratch.

## What to build

1. **A new onboarding flow/page** (`src/app/capability-onboarding/` or
   fold into an existing "Studio"-style page if you judge one fits better
   — `src/app/novus-studio/` and `src/app/policy-studio/` are the
   existing "guided multi-step flow" pages in this app, worth a look for
   layout/interaction conventions before deciding). A step-indicator
   wizard driven directly by the session's real `status` field (not
   separate client-side wizard state that can drift from the backend) —
   Turn 1 form → tool picker + domain/capability_id form → risk summary
   confirm → sandbox test runner with input editor → final activate
   confirm.
   - Turn 1: URL input + optional track override.
   - Turn 2: render `report.tools` as a selectable list (name +
     description + a collapsed view of `input_schema`), then a small
     form for `domain`, `capability_id`, `version`, `estimated_cost_usd`,
     and — only shown when `track === "openapi"` — `test_base_url` /
     `production_base_url`.
   - Turn 3: show the computed risk tier + reasoning, one confirm
     button.
   - Turn 4: a JSON/form editor for `sample_input` (shape depends on the
     tool's `input_schema` — a generic JSON textarea is an acceptable v1,
     doesn't need per-field schema-driven inputs), the
     `acknowledge_live_call` checkbox gated to appear only for `openapi`,
     a "run sandbox test" button, and a result panel showing
     `evidence_summary` (pass/fail styled distinctly) with `raw_output`
     collapsed by default.
   - Turn 5: final review summary (capability_id, domain, risk tier,
     sandbox evidence) + activate button.
2. **A sessions list/history view** — table or card list from
   `GET /capability-onboarding/sessions`, showing id/source_url/track/
   status/created_by/created_at, status shown as a colored badge (reuse
   whatever badge/status-color convention `CapabilityManifestRegistryPanel`
   or `CircuitBreakerCard` already established — do **not** invent new
   ad hoc Tailwind color classes; this codebase has a real, specific bug
   history around that, e.g. a past `bg-${color}/20` template-string bug
   where a badge silently rendered with no color at all because the
   token didn't match Tailwind's static class scanner — always use full
   literal class names from a static lookup object). Clicking a row opens
   the session detail (its full audit log + whichever step it's currently
   at — if not yet `activated`/`failed`/`aborted`, let them resume the
   wizard from that exact step).
3. **Link it in from somewhere sensible** — the integrations page
   already has a `CapabilityManifestRegistryPanel` showing *activated*
   capabilities; a natural spot is a nearby "Onboard a new capability"
   CTA that routes into this new flow. Use your judgment on exact
   placement/nav entry, just make it discoverable, not an orphan route.

## Explicitly not your job this round

- No raw-code onboarding track UI — it doesn't exist on the backend yet
  (being built separately, in parallel, right now). Don't add a third
  tab/option for it.
- ~~No UI for supplying real tool-call *arguments* to an activated
  capability at MOA-invocation time — that's a backend protocol gap
  being worked on separately and has no API surface yet either.~~ **This
  is now closed on the backend and IS real, buildable work — see the
  addendum at the bottom of this doc.** It does not belong in this
  onboarding wizard's own UI (different page entirely — see the
  addendum for exactly where), so it's still not part of "what to build"
  above; it's flagged here only because this doc is where the original
  gap was noted.
- Don't touch `CapabilityManifestRegistryPanel` or `CircuitBreakerCard`
  themselves beyond reading them for convention — they're stable,
  already correct, out of scope here.

## When you're done

- `npm run build` and `tsc --noEmit` clean.
- Walk through all 5 turns live against the real running backend (`docker
  compose up -d`, backend on `:8000`, `npm run dev` for the frontend) —
  onboard something real end to end and confirm the session ends up
  `activated` and shows correctly in both the new list view and (if you
  add a capability_id that shows up there) `CapabilityManifestRegistryPanel`.
  A tiny local test fixture exists at
  `tests/fixtures/mcp_native_sample/` (a real 4-tool FastMCP server) if
  you want a fast, no-external-network source to onboard against —
  `source_url` can be that local absolute path, it doesn't have to be a
  real GitHub URL.
- Exercise at least one real failure path live (e.g. submit a garbage
  `source_url` at Turn 1, or omit `test_base_url` on an OpenAPI-track
  Turn 2) and confirm the UI degrades the way this doc specifies, not
  just a generic error toast.

---

## Addendum (2026-08-05) — editing a paused MOA action's arguments before approving

This is a **separate feature on a separate page** — nothing here touches
the onboarding wizard above. It's appended to this doc only because this
doc is where "no UI for supplying real tool-call arguments at
MOA-invocation time" was originally flagged as out of scope. That backend
gap is now closed for real; this is the concrete, buildable frontend spec
for it.

### The problem this closes

Once a capability is onboarded (the wizard above) and MOA picks it, the
LLM proposes real per-call *arguments* too, not just which action to run
(e.g. `add_numbers` with `{"a": 4, "b": 5}`) — this already works and is
already returned in every `pending_approval` response's `proposedAction`.
But the LLM can propose the wrong values, and today the human reviewer's
only options are "approve exactly what the model picked" or "reject the
whole action" — no way to correct e.g. a wrong amount before it executes.
The backend now supports a third option: approve with a correction.

**Where this lives in the frontend:** the "HELD ACTION APPROVAL CARD" in
`frontend-next/src/components/jarvis/LangGraphAgentWorkspace.tsx` (around
line 239 as of this writing) — the card that renders when
`moaResult.status === "pending_approval"`. That's the MOA tab of the
`/jarvis` workspace, not anything under `capability-onboarding/`.

### What changed on the backend (already shipped, read-only for you)

`proposedAction` (in every `POST /moa/tasks`, `/moa/tasks/{id}/approve`,
`/moa/tasks/{id}/reject` response that pauses again) now carries two more
fields your current TypeScript type doesn't declare yet:

```ts
// frontend-next/src/lib/api.ts's MOATaskResponse["proposedAction"] —
// add these two fields to the existing type
proposedAction?: {
  action_key: string;
  capability: string;
  summary: string;
  estimated_cost_usd: number;
  policy_tier: PolicyTier;
  arguments: Record<string, unknown>;       // NEW — the LLM's own proposed argument values, e.g. {"a": 4, "b": 5}. Empty object for every built-in HR/IT/Finance/Manufacturing action today (none of them take real per-call params beyond the fixed employee_name) — only onboarded/dynamic capabilities have real ones.
  input_schema: Record<string, unknown>;    // NEW — JSON Schema for `arguments` (same shape as DiscoveredTool.input_schema above). {} when the action takes no real parameters.
};
```

`POST /moa/tasks/{id}/approve` now optionally accepts a JSON body:

```ts
{ edited_arguments?: Record<string, unknown> }
```

- **Omit it entirely, or send `{}`** (or `{"edited_arguments": null}`) —
  behaves exactly as before: the action executes with the LLM's own
  `arguments` unchanged. `reject` is untouched, takes no body, don't add
  one.
- **Send `{"edited_arguments": {...}}`** — those values **fully replace**
  `proposedAction.arguments` (not merged — send the complete corrected
  object, every field, not just the ones you changed). Validated against
  `proposedAction.input_schema`'s `required` array before anything
  executes.
- **422 response** — `detail` is a human-readable message, e.g.
  `"edited_arguments is missing required parameter(s): ['b']"`. The task
  is still genuinely pending afterward (not consumed) — same "fix and
  resubmit" pattern the wizard above already uses for a failed sandbox
  test. Keep the card open with whatever the reviewer typed, don't clear
  the form.
- **400 response** — malformed JSON body, or `edited_arguments` present
  but not a JSON object (e.g. a string or array) — same recovery: task
  still pending, keep the form open.

### What to build

1. When `proposedAction.input_schema.properties` is non-empty, render an
   editable form for `proposedAction.arguments` under the existing
   Action/Summary/Estimated Exposure block — one input per schema
   property (checkbox for `boolean`, number input for `integer`/`number`,
   text input otherwise is an acceptable v1; a generic JSON textarea,
   same as the onboarding wizard's Turn 4 `sample_input` editor above, is
   also acceptable and less work — your call), pre-filled with the LLM's
   own `arguments` values so the reviewer edits rather than starts blank.
   Mark fields listed in `input_schema.required` visually as required.
2. When `input_schema.properties` is empty/absent (every built-in action
   today), render nothing new — the card should look exactly as it does
   now. Don't show an empty "no parameters" form.
3. Wire the "✅ Approve & Resume Execution" button to send the edited
   values: extend `api.approveMOATask` (`frontend-next/src/lib/api.ts`)
   to take an optional second argument and forward it as the request
   body —
   ```ts
   approveMOATask: (taskId: string, editedArguments?: Record<string, unknown>) =>
     apiFetch<MOATaskResponse>(`/moa/tasks/${taskId}/approve`, {
       method: "POST",
       body: JSON.stringify(editedArguments ? { edited_arguments: editedArguments } : {}),
     }),
   ```
   and pass the form's current values through
   `moaApproveMutation.mutate(taskId, editedArguments)` only when the
   reviewer actually changed something from the LLM's original proposal —
   sending the unedited `arguments` back verbatim is harmless (identical
   to omitting it) but sending it unconditionally is fine too if that's
   simpler; either is correct.
4. On a 422/400 from the approve mutation, surface `detail` inline in the
   card (not a generic toast — matches this doc's existing "errors the UI
   must handle explicitly" convention for the wizard above) and leave the
   form populated with whatever the reviewer typed so they can fix and
   resubmit, rather than clearing it back to the LLM's original values.

### Explicitly not part of this either

- No editing of `action_key` itself (which action runs) or `policy_tier`
  — only the argument *values* for the already-chosen action are
  editable.
- Reject still takes no body and is unaffected by any of this.
- Static HR/IT/Finance/Manufacturing actions have no real parameters
  today (see `input_schema` above) — you will not see this form appear
  for them in practice; that's expected, not a bug to chase.
