# Phase 2 handoff — Antigravity kickoff prompt

Coordination note, not an RFC chapter: this is the prompt to paste into
Antigravity to start Phase 2 while Claude Code builds Phase 1 in parallel.
See [000-vision.md](000-vision.md#roadmap) for the phase list and the
dependency analysis that justified running these two in parallel.

---

```
You're starting Phase 2 of ADOS (Autonomous Defect & Orchestration System),
an enterprise decision operating system for manufacturing/supply chains.
Someone else (Claude Code) is building Phase 1 (FastAPI backend, event bus,
contracts, Integration Hub, auth) at the same time, in the same repo. You
are NOT blocked on their work, but you must build against the interfaces
they've already written down so the two halves integrate later without
rework.

READ FIRST (in this order):
1. docs/000-vision.md — the decision loop and why this system exists
2. docs/001-system-architecture.md — the six-layer architecture; you own L2
3. docs/002-knowledge-graph.md — Enterprise Knowledge Graph design
4. docs/003-causal-graph.md — Causal Graph design + calibration loop
5. docs/004-agent-framework.md — the agent contract every agent must implement
6. docs/010-api-contracts.md — the event/capability envelope you must honor
7. adr/0007-separate-knowledge-and-causal-graphs.md — why these are two
   stores, not one

YOUR SCOPE (Phase 2, per docs/000-vision.md roadmap):
- Enterprise Knowledge Graph (knowledge/) — entity/relationship store per
  docs/002-knowledge-graph.md: Product, Part, Supplier, Facility,
  Specification, Substitution nodes; query surface
  (findAffectedProducts, findApprovedSubstitutes, getSpecification)
- Causal Graph (knowledge/) — weighted condition->outcome model per
  docs/003-causal-graph.md, with rankCandidateCauses() and the
  calibration hook the Feedback & Calibration Agent will use
- Digital Twin (knowledge/ or a new digital-twin/ module if it doesn't fit
  the existing stores — your call, note the decision in a short ADR)
- Agent SDK (agents/) — implement the agent roster from
  docs/004-agent-framework.md's table (Vision & Spec, Causal Isolation,
  CAD & Spec Comparison, Substitution, Parameter Adjustment, Impact
  Simulation, Re-routing, Feedback & Calibration), each conforming to the
  Agent contract: input IncidentContext + StageInput, output
  { result, confidence, evidence[], alternatives[] }, built on IBM ADK.

CONTRACT YOU MUST HONOR (so Phase 1 can integrate without changes):
- Event envelope and capability-call envelope exactly as specified in
  docs/010-api-contracts.md — every event you emit needs eventId,
  eventType, incidentId, occurredAt, producedBy, schemaVersion, payload.
- Agent contract's confidence/evidence[]/alternatives[] fields are
  mandatory, not optional — docs/007-governance.md's approval gate reads
  them directly.
- If you need a new event type or capability that isn't already in
  contracts/, don't invent the schema unilaterally: add it under
  contracts/ following the envelope rule, and flag it clearly (e.g. a
  `status: proposed` field or a note at the top of the file) so Phase 1
  can review it rather than silently diverging.

STAY OUT OF (Phase 1 / Claude Code's territory, to avoid collisions):
- backend/, orchestrate/, integrations/ — don't implement these, only
  assume their documented contracts exist.
- Don't change docs/001, docs/005, docs/006, docs/007, docs/009, docs/010
  without flagging it — those are shared/cross-cutting; propose changes as
  an open question in the relevant chapter instead of editing the decision
  outright.

SKILLS:
This project has the antigravity-awesome-skills collection available.
Install it into your own skills directory (not the repo — it's gitignored
here since Claude Code's copy is scoped to .claude/skills for its own use):

    npx antigravity-awesome-skills --antigravity

That installs to ~/.gemini/antigravity/skills by default. Once installed,
invoke skills with @skill-name. Ones directly relevant to this scope:

- @ai-agents-architect — designing the agent roster and their boundaries
- @multi-agent-patterns / @agent-orchestration-multi-agent-optimize — how
  the agents should be structured given they're sequenced by an external
  orchestrator (Phase 1), not calling each other directly
- @database-architect — Knowledge Graph / Causal Graph store design
- @pydantic-models-py — typed schemas for the agent contract and graph
  query surface (Python + IBM ADK)
- @prompt-engineering-patterns / @prompt-library — agent prompts for
  Vision & Spec, Causal Isolation, CAD & Spec Comparison agents
- @llm-evaluation / @agent-evaluation — confidence scoring and validating
  the Causal Graph calibration loop against held-out incidents
- @event-sourcing-architect — background for the event envelope you're
  consuming from Phase 1, even though you're not implementing the bus

DELIVERABLES FOR THIS PASS:
1. Knowledge Graph: entity schema + the three query functions from
   docs/002-knowledge-graph.md, with a small seed dataset for local dev.
2. Causal Graph: condition/outcome model + rankCandidateCauses(), with
   the priors seeded from the MVP demo flow's example (tolerance drift ->
   dimensional fault, etc. per docs/003-causal-graph.md).
3. Agent SDK skeleton: the shared Agent contract as a typed interface, plus
   one fully working agent end-to-end (recommend starting with Causal
   Isolation Agent, since it exercises both graphs) to validate the
   contract before filling in the rest of the roster.
4. A short status note (docs/002 / docs/003 "Open Questions" sections, or
   a new ADR if you made a real architectural call) describing anything
   you decided that this brief didn't already pin down.

Ask before doing anything that would change the event/capability contract
shape in a way Phase 1 would need to react to — that's the one place
where "parallel" breaks if we're not careful.
```
