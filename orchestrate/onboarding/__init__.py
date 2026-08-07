"""
Capability Onboarding — orchestration-platform-vision.md §8, "Bring Your
Own Capability". Turns a GitHub repo URL (or local path) into a governed,
MOA-callable capability: inspect -> synthesize -> risk-proposal ->
sandbox-test -> activate.

This build pass covers the MCP-native and OpenAPI tracks only. Raw-code
onboarding (an LLM writes a wrapper for arbitrary code, then executes it)
is deliberately deferred — no sandbox-isolation precedent existed anywhere
in ADOS before this package, and it's the single highest-risk piece of the
full §8 spec; see ADOS_OBSIDIAN/TODO - Orchestration Platform Pivot.md for
the tracked follow-up. Both tracks built here call an existing
self-describing interface (the target repo's own MCP server, or a
documented OpenAPI spec) rather than authoring and executing fresh code.

See integrations/connectors/dynamic.py and orchestrate/moa/dynamic_registry.py
for the other two-thirds of the bridge this package feeds: the former makes
an onboarded capability invocable, the latter makes it choosable by MOA's
reasoning loop; this package is what actually produces one.
"""
