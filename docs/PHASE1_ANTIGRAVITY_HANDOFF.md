# ADOS Phase 1 — Multi-Line Digital Twin (Context Prompt for Antigravity)

Paste this whole document as your starting context. It is self-contained —
you don't need anything from a prior conversation.

## Project

ADOS (Autonomous Defect & Orchestration System) is a multi-agent AI system
for manufacturing defect detection and root-cause resolution. Repo root:
`/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS`
(now a git repo; latest commit `4bfb4f8` is your starting point — run
`git log --oneline` to confirm you're on top of it before editing).

Read `docs/handoff.md` first for full system architecture and completed
phases (1 through 4B are done, 68+ tests passing). Read
`Blueprints/ADOS_Demo_Product_Experience_Blueprint.md` for the judge-facing
demo narrative this whole effort is building toward: a "Mission Control"
dashboard for **Nova Motors**, where a Motor Housing quality incident on
**Line 2** gets investigated and resolved end-to-end by ADOS in minutes.

## What just landed (Phase 0 — not your job, already done)

A parallel workstream just rewrote the demo dataset with Nova Motors
branding: 5 products, 5 machines, 5 suppliers, and ~100 seeded incidents
across 8 causal categories. This touched `knowledge/seed_data.py`,
`executive/seed_data.py`, `executive/incident_generator.py`,
`knowledge/causal_graph.py`, and a few agent files. **Do not touch those
files** — there's no import dependency between them and your files, so
there's no merge conflict, but you must **reuse their naming scheme exactly**
(below) so the two datasets stay logically consistent.

## Your job: Phase 1 — multi-line Digital Twin

Right now `knowledge/digital_twin.py` and `knowledge/asset_model.py` each
hardcode a **single** production line ("Line 3") independently (no shared
import between them — they're two separate hardcoded seeds). The blueprint's
demo requires **Line 1, Line 2, Line 3, and Warehouse** all visible and
live-updating. Your deliverables:

1. **`knowledge/digital_twin.py`**: extend `DigitalTwinStore._initialize_seed_lines()`
   (currently lines 47-87) to seed all four lines instead of just Line 3.
   Keep the existing `FactoryLineState` / `MachineParameter` pydantic models
   unchanged — just add more `FactoryLineState` entries to `self._lines`.
   Keep the existing Line 3 entry as-is (it's the "currently degraded"
   line other tests already depend on — see `tests/test_phase2_integration.py`
   `test_digital_twin_operations`, which calls `dt.get_line_state("Line 3")`
   expecting `status == "DEGRADED"`. Don't change that.).

2. **`knowledge/asset_model.py`**: extend `EnterpriseAssetModel._seed_ground_truth()`
   (currently lines 125-152) so `Factory("FAC-P1")` has all four `Line`
   entries (with realistic `Machine` → `PLC` → `Sensor` chains per the
   naming table below), not just Line 3. **Important existing-data bug to
   fix while you're in there**: the current seed hardcodes
   `Component(partNumber="P-1002", specId="SP-1002", approvedSupplierIds=["S-201","S-202"])`
   and `AssetProduct(sku="PROD-500", lineId="Line 3", ...)`. Those IDs are
   now stale — Phase 0 renamed the housing part to `MH-100`/`SP-100`, its
   suppliers to `SUP-201`/`SUP-202`, and reassigned `PROD-500` to Gear
   Assembly (now Line 1). Update this component/product to
   `partNumber="MH-100"`, `specId="SP-100"`, `approvedSupplierIds=["SUP-201","SUP-202"]`,
   and `AssetProduct(sku="PROD-100", name="Motor Housing", lineId="Line 2", ...)`.

3. **New backend route**: add `GET /digital-twin/lines` (new router file,
   e.g. `backend/app/routers/digital_twin.py`, wired into
   `backend/app/main.py` the same way `learning.py` was wired in — see
   `docs/handoff.md` §2 "Phase 4 Dashboard Surfacing" for that exact pattern
   including the `Depends(require_service_auth)` requirement every other
   router has). It should return all four lines' current state from
   `DigitalTwinStore`.

4. **Frontend**: add a small colored status strip to the existing ops
   dashboard (`frontend/index.html` / `app.js` / `styles.css`) showing the
   four lines and their status (🟢 OPERATIONAL / 🟡 DEGRADED / 🔴 STOPPED),
   polling `GET /digital-twin/lines`. Keep it small — this is not the full
   "Mission Control" narrative page (that's a later phase), just a live
   status strip on the current debug dashboard.

5. **Tests**: update `tests/test_asset_model.py` (hardcodes `PLANT-NA-01`,
   `FAC-P1`, `Line 3`, `CNC-SPINDLE-03`, `PLC-CNC-03`, `SNS-VIB-45`, and an
   exact lineage-path string — extend/adjust for the new lines and the
   `MH-100`/`PROD-100` rename, don't just delete assertions) and confirm
   `tests/test_phase2_integration.py::test_digital_twin_operations` still
   passes unmodified. Add new tests for the new lines' lineage resolution
   and `GET /digital-twin/lines`.

## Shared naming scheme (must match exactly — do not invent your own names)

| Line | Facility ID | Cell | Machine(s) | Product on this line |
|---|---|---|---|---|
| Line 1 | `FAC-P1-L1` | Cell 1-A (Assembly) | Robot Arm, Assembly Line | Cooling Plate (`PROD-400`), Gear Assembly (`PROD-500`) |
| Line 2 | `FAC-P1-L2` | Cell 2-A (Machining & Fitting) | CNC-101, Inspection Cell | **Motor Housing (`PROD-100`)** — this is the hero incident line |
| Line 3 | `FAC-P1-L3` | Cell 3-A (Machining) | CNC-102 | Rotor (`PROD-200`), Bearing (`PROD-300`) |
| Warehouse | `FAC-P1-WH` | Cell WH-1 (Inventory Staging) | — (no machine) | inventory staging for all parts |

Plant: single plant, `plant_id="PLANT-NA-01"` (asset_model.py) /
`plant_name="Nova Motors - Detroit Plant"` (matches `knowledge/seed_data.py`'s
`Facility` entries — Factory stays `FAC-P1`, region North America).

Suppliers (already seeded in `knowledge/seed_data.py`, for reference only —
you don't touch this file): `SUP-201` PrecisionCast, `SUP-202` SteelCore,
`SUP-203` Titan Metals, `SUP-204` ForgeWorks, `SUP-205` Rapid Components.

Products (already seeded, for reference): `PROD-100` Motor Housing (Line 2),
`PROD-200` Rotor (Line 3), `PROD-300` Bearing (Line 3), `PROD-400` Cooling
Plate (Line 1), `PROD-500` Gear Assembly (Line 1).

## Verification

```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
./.venv/bin/pytest tests/ backend/tests/ -q
```

All tests must stay green (75 currently pass on top of your starting
commit). Also manually hit the new endpoint and eyeball the dashboard:

```bash
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
# open http://localhost:8000/dashboard/, token: dev-local-only-token
```

## Known rough edge, optional but worth a look

`agents/rerouting_agent.py`'s `process()` hardcodes the strings `"Line 3
PLC"` and an alternative `"OPT-REROUTE-LINE-4"` / `"Detroit Plant Line 4"`
in its output regardless of the actual `context.line_id` passed in, and
there is no Line 4 in this dataset. Since you're the one touching
line-topology code in this phase, consider making that text dynamic
(interpolate `target_line`) and dropping the Line 4 reference — but this is
not required for Phase 1 to be considered done; flag it if you'd rather
leave it for a later cleanup pass.

## Do not touch

`knowledge/seed_data.py`, `executive/seed_data.py`,
`executive/incident_generator.py`, `knowledge/causal_graph.py`,
`agents/causal_isolation_agent.py`, `agents/substitution_agent.py`,
`agents/cad_spec_agent.py`, `agents/impact_simulation_agent.py`,
`executive/predictive_risk.py`, `executive/recommendation_engine.py`,
`integrations/connectors/marketplace.py`, `executive/copilot.py`,
`scripts/run_demo_pipeline.py`, `scripts/run_orchestrator_demo.py`,
`scripts/run_phase3b_demo.py`, and
`tests/test_phase2_integration.py` / `test_phase3b_integration.py` /
`test_phase4a_integration.py` / `test_phase4b_integration.py` (except the one
already-passing digital-twin assertion noted above, which you must not
break, not "not touch" — you don't need to edit it, just don't regress it).

When done, commit your changes with a clear message (this is a plain local
git repo, no remote yet) so the two workstreams can be diffed and merged
cleanly.
