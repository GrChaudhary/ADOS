# frontend/

The two L6 user surfaces: the Tier 1/2 approval surface and the Executive
Intelligence Dashboard, plus the shared incident timeline component both
depend on.

Relevant chapters: [011-ui-ux](../docs/011-ui-ux.md),
[008-executive-intelligence](../docs/008-executive-intelligence.md),
[007-governance](../docs/007-governance.md) (required evidence fields the
approval surface must render).

Roadmap: Phase 3 (Executive Dashboard, Recommendation Engine surfaced in
UI).

## Status: running

Plain HTML/JS, no build step — `index.html`, `app.js`, `styles.css`.
Served by the backend itself at `/dashboard/` (`backend/app/main.py`
mounts this directory via `StaticFiles`), so `app.js`'s `fetch()` calls
hit `/incidents`, `/approvals`, `/executive/*` on the same origin with no
CORS setup needed.

```bash
../scripts/run-backend.sh
# open http://localhost:8000/dashboard/
```

Enter the service token (`SERVICE_AUTH_TOKEN`, defaults to
`dev-local-only-token`) once — it's kept in `localStorage`. From there:
start an incident, watch it land in **Pending Approvals**, approve/reject/
escalate it, and see it move into **Recent Incidents** and the **Executive
KPIs**/**Recommendations**/**Predictive Risk** panels, all polling every
4s. **Executive Copilot** is a free-text query box against
`POST /executive/copilot/ask`.

Every field name here was checked against the live API response, not
guessed — `executive/models.py`'s `StrategicRecommendation`/`RiskSignal`
mix aliased (camelCase) and unaliased (snake_case) fields inconsistently
(e.g. `impact_level`, `risk_score` have no alias while `estimatedAnnualSavingsUsd`
does); `app.js` matches what's actually returned, not what the naming
convention elsewhere would suggest.
