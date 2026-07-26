# ADOS Phase 5B — 5 Remaining Screens (Context Prompt for Antigravity)

Paste this whole document as your starting context. It is self-contained —
you don't need anything from a prior conversation.

## Project

ADOS (Autonomous Defect & Orchestration System) is a multi-agent AI system
for manufacturing defect detection and root-cause resolution, for **Nova
Motors, Plant 04 (Austin, TX)** — an EV powertrain assembly facility
producing the **EV-POW-800V** (800V Electric Drive Unit). Repo root:
`/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS`
(git repo — run `git log --oneline` and confirm you're on top of the latest
`Phase 5 pivot Step 4` commit before editing).

Read `documentation/01_Product_Design_Specification.md` (screen specs),
`documentation/02_Demo_Dataset_and_Digital_Twin.md` (the real dataset),
`documentation/03_Design_System.md` (design tokens — already implemented,
see below), `documentation/04_Demo_UI_Architecture.md` (frontend
architecture), and `documentation/05_Product_Bible.md` (system + governance
reference) — these are the actual product specs this whole rebuild follows.

## What just landed (not your job, already done)

Mid-project, the whole frontend was rebuilt from a plain-HTML/JS demo page
into a real **Next.js 16 (App Router) + TypeScript + Tailwind v4 + TanStack
Query + Zustand** app at `frontend-next/`, alongside a dataset rename
(Nova Motors Detroit → Plant 04 Austin TX) and a governance rewrite
(`orchestrate/governance.py` now uses the dollar-threshold tier matrix from
`documentation/05`'s section 5, not the old risk-class model). None of that
is yours to redo — **do not touch** `orchestrate/governance.py`,
`knowledge/*.py`, `executive/*.py` (the Python backend/dataset), or
`frontend-next/src/app/digital-twin/*` and
`frontend-next/src/app/incidents/[incidentId]/*` (the other builder's two
screens — Mission Control and the Incident Workspace).

The backend now serves every real endpoint under **both** its original
path and a `/api/v1/...` alias (`backend/app/main.py`) — e.g.
`/executive/kpis` and `/api/v1/executive/kpis` return identical data, same
router, same auth. CORS is configured for `http://localhost:3000`
(`backend/app/config.py`'s `frontend_dev_origin`).

## Your job: the 5 remaining screens

`documentation/01_Product_Design_Specification.md` section 4 specs 7
screens total; 2 are done (Mission Control/Digital Twin, Incident
Workspace). You own the other 5, each already has a **working placeholder
route** using the shared design system — replace the placeholder body,
don't touch routing/shell:

1. **Executive Intelligence Command Center** — `frontend-next/src/app/executive/enterprise/page.tsx`. Spec: doc 01 Screen 1. Data: `GET /executive/enterprise` (`ExecutiveIntelligenceSummary`), `GET /executive/kpis`, `GET /executive/kpis/what-if?condition_id=` (the Autonomy Simulator slider), `GET /executive/risk` (Supplier Risk Radar).
2. **Agent Swarm Network & Lineage View** — `frontend-next/src/app/agents/network/page.tsx`. Spec: doc 01 Screen 4. The 8 agents' metadata (icon, color, label) is already defined once in `frontend-next/src/lib/agents.ts` (`AGENTS` record, keyed by real `agent_id` strings like `"vision-spec-agent"`) — **reuse it**, don't redefine. No dedicated backend endpoint exists for "agent network/lineage" data; synthesize the view from `GET /events?limit=200` (recent `AgentCompleted` events across incidents) grouped by `payload.agentId`/`payload.agentIdId` (see casing note below) for latency/confidence distributions.
3. **Decision Memory & Causal Learning Hub** — `frontend-next/src/app/memory/page.tsx`. Spec: doc 01 Screen 5. Data: `POST /memory/search` (vector-ish precedent search — see `contracts/decision_memory_query.py` for the request shape), `GET /learning/recalibration` (causal edge weight history), `GET /learning/promotion-candidates` (Tier 0 promotion candidates — note: written before the governance rewrite, still risk-class-flavored language, that's fine, don't change it).
4. **Governance Policy & Autonomy Administration** — `frontend-next/src/app/governance/page.tsx`. Spec: doc 01 Screen 6. This is the real dollar-threshold matrix now (`_LOW_EXPOSURE_MAX_USD=25_000`, `_HIGH_EXPOSURE_MIN_USD=250_000`, `_TIER0_CONFIDENCE_THRESHOLD=0.90` in `orchestrate/governance.py`) — display it, but there's **no backend endpoint to read or mutate these thresholds live** today; render them as read-only reference values (import nothing from Python, just hardcode the same three numbers with a comment citing `orchestrate/governance.py`) rather than building a fake working slider that doesn't actually call anything. The "Emergency Override Soft Lock" in the spec has no backend support either — a disabled/decorative control is honest here, a wired-up one that silently does nothing is not.
5. **Enterprise Integration Monitor** — `frontend-next/src/app/integrations/page.tsx`. Spec: doc 01 Screen 7. No live connector health endpoint exists; `integrations/hub.py` and the connectors (`integrations/connectors/watsonx_itsm.py`, `sap.py`, `marketplace.py`) are real but there's no REST surface exposing their health/latency. Render static "Connected" status cards (matching `FooterStatusBar`'s existing copy) rather than fabricating live metrics with no data source — same principle as #4.

## Conventions already established — reuse, don't reinvent

- **Design tokens**: `frontend-next/src/app/globals.css` has the full `documentation/03_Design_System.md` palette as CSS custom properties, wired into Tailwind v4's `@theme inline` block (this Next.js/Tailwind version has **no `tailwind.config.ts`** — themes are CSS-native now, not JS). Use classes like `bg-app`, `text-emerald`, `border-border-subtle` directly. **Important Tailwind gotcha already hit once**: Tailwind's scanner only detects class names that appear as **literal strings** in source — `` className={`text-${color}`} `` will never generate CSS. Use a static lookup object instead (see `frontend-next/src/components/design-system/KpiCard.tsx`'s `ACCENT_TEXT_CLASS` for the pattern).
- **Shared shell**: `frontend-next/src/components/design-system/AppShell.tsx` (+ `Sidebar.tsx`, `HeaderTelemetryBar.tsx`, `FooterStatusBar.tsx`) wraps every route via the root `layout.tsx` — you don't need to build any of this, your `page.tsx` files just return their content body.
- **Shared components**: `KpiCard.tsx`, `StatusPulse.tsx`, `OptionCard.tsx` in the same folder — reuse where they fit (e.g. `KpiCard` for your Executive screen's summary bar) rather than building parallel versions.
- **API client**: `frontend-next/src/lib/api.ts` — add your endpoints' functions to the same exported `api` object, don't create a second client. **Read the module docstring before writing any fetch calls** — the real backend's JSON casing is genuinely inconsistent field-by-field (some pydantic models are camelCase via alias, a few fields on those same models have no alias and stay snake_case, some hand-built dict endpoints are snake_case throughout). Every type in that file is written literally as it appears on the wire, verified against the actual router/model source — trust those types, don't assume uniform camelCase. For any new endpoint you add (e.g. `/executive/risk`, `/memory/search`, `/learning/recalibration`), read the actual FastAPI router (`backend/app/routers/executive.py`, `memory.py`, `learning.py`) and its pydantic response models before typing it — don't guess field names.
- **Auth**: `getToken()`/`setToken()` in `lib/api.ts`, same `localStorage` key (`ados_service_token`) as the old plain-JS dashboards, entered via `HeaderTelemetryBar`'s input — already wired, just call `api.whatever()` and it'll authenticate itself.
- **SSE, if you need it**: `openIncidentEventStream()` in `lib/api.ts` connects directly to the backend origin (not the Next.js rewrite proxy — `EventSource` can't reliably traverse a rewrite for a long-lived stream, and can't set an `Authorization` header, hence the `?token=` query param). If your Agent Swarm view wants live agent activity, this is reusable, but consider whether a periodic `GET /events` poll is simpler for a cross-incident aggregate view (SSE is filtered per-incident server-side today, not global).
- **No backend changes**: everything above is read-only consumption of what exists. If a screen's spec calls for something with genuinely no backend support (see #4/#5 above), render it honestly as static/reference content — do not add new FastAPI routes or modify Python files as part of this phase.

## Verification

```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/frontend-next"
npm run build   # must have zero TypeScript errors
npm run dev     # :3000
```
Backend: `cd .. && ./.venv/bin/uvicorn backend.app.main:app --reload --port 8000` (token: `dev-local-only-token`). Confirm your 5 routes render real data (or honest static content per #4/#5) with no console errors, and that the shared shell/nav still works correctly navigating to and from your screens.

## Do not touch

`orchestrate/governance.py`, `knowledge/*.py`, `executive/*.py`,
`backend/app/main.py`, `backend/app/config.py`,
`frontend-next/src/app/digital-twin/*`,
`frontend-next/src/app/incidents/[incidentId]/*`,
`frontend-next/src/app/layout.tsx`,
`frontend-next/src/components/design-system/AppShell.tsx` (and its
Sidebar/Header/Footer siblings), `frontend-next/src/lib/api.ts`'s existing
functions (adding new ones is fine), `frontend-next/src/app/globals.css`
(the token values — adding new component-scoped classes is fine),
`frontend/` (the old plain-JS dashboards, kept as-is, unrelated to this
rebuild).

When done, commit your changes with a clear message.
