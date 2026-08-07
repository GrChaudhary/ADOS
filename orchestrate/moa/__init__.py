"""
MOA (Main Orchestrating Agent) — orchestration-platform-vision.md §3 and
§11 build-sequence step 2: dynamic, ReAct-style planning ("decide the next
action based on the outcome of the previous one", not a pre-baked plan)
with action-level governance (every action submitted for a verdict before
it executes, not one approval for a whole upfront plan).

This is a vertical-slice proof on one domain pod (HR — see hr_domain.py),
not the full platform vision: no cross-domain arbitration, no capability
onboarding meta-agent, no weighted risk-scoring pipeline. Those are
separate, still-open milestones.

Reuses, rather than reinvents, two things that already existed but had
nothing to call them yet:
    - The interrupt()/Command(resume=...) pause-for-governance pattern
      already proven in orchestrate/langgraph_agents/itsm_agent.py.
    - orchestrate/governance.py's assign_policy_tier() and
      orchestrate/cascade_breaker.py's CascadeCircuitBreaker — both
      already per-action-shaped; this package is what finally wires them
      into a real multi-action loop.
"""
