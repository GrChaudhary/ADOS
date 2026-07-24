# Diagrams

Mermaid sources for the diagrams embedded in the `docs/` chapters. Each file
is also inlined directly in its owning chapter (GitHub, and most Markdown
viewers, render Mermaid fences natively) — the `.mmd` files here exist so
the diagram can be edited or rendered standalone without extracting it from
prose.

| File | Used in |
|---|---|
| [layered-architecture.mmd](layered-architecture.mmd) | [001-system-architecture](../001-system-architecture.md) |
| [incident-state-machine.mmd](incident-state-machine.mmd) | [005-decision-orchestrator](../005-decision-orchestrator.md) |
| [decision-loop.mmd](decision-loop.mmd) | [000-vision](../000-vision.md) |

## Convention

When a diagram changes, update the `.mmd` source here **and** the inline
copy in the chapter — keep them identical. If they ever drift, the chapter
copy is authoritative (it's the one reviewed alongside the prose that
explains it).
