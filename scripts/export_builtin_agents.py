import os
import yaml
from backend.app.routers.agents_registry import BUILTIN_AGENTS

# Ensure output directory exists
OUTPUT_DIR = "orchestrate/builtin_agents"
os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"Generating agent YAML specifications in '{OUTPUT_DIR}'...")

for agent in BUILTIN_AGENTS:
    # Format name to be a clean snake_case slug
    agent_slug = agent.id.replace("-", "_")
    
    # Map stage to logical collaborator tools / descriptions
    spec = {
        "spec_version": "v1",
        "kind": "native",
        "name": f"ados_{agent_slug}",
        "description": agent.description,
        "context_access_enabled": True,
        "context_variables": [],
        "llm": "ibm/granite-3-8b-instruct",
        "style": "default",
        "instructions": agent.instructions or agent.description,
        "collaborators": [],
        "tools": [],
        "plugins": {},
        "knowledge_base": []
    }
    
    # Save as YAML
    filepath = os.path.join(OUTPUT_DIR, f"ados_{agent_slug}.agent.yaml")
    with open(filepath, "w") as f:
        yaml.safe_dump(spec, f, default_flow_style=False, sort_keys=False)
    
    print(f"  - Generated ados_{agent_slug}.agent.yaml")

print("\nTo import all 8 agents to your active watsonx Orchestrate environment, run:")
print("----------------------------------------------------------------------")
print("for f in orchestrate/builtin_agents/*.agent.yaml; do")
print("  ./.venv/bin/orchestrate agents import -f \"$f\"")
print("done")
print("----------------------------------------------------------------------")
