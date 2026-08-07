"""
LangGraph-based replacements for the agents that used to run on IBM
watsonx Orchestrate — see orchestration-platform-vision.md's decision to
remove that dependency entirely (ADR-0002, superseded). Each agent here
replaces one *.agent.yaml + tools pair from orchestrate/:

    ados_executive_copilot.agent.yaml + watsonx_tools.py
        -> executive_copilot.py

Deliberately does NOT touch orchestrate_langgraph/ (a separate, unrelated
module — that one is last session's head-to-head evaluation of LangGraph
vs. the custom L4 state machine engine for the *core* incident pipeline,
already decided against; this package has nothing to do with that
decision and exists purely to replace the IBM-hosted pieces).
"""
