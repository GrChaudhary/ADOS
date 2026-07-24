# infrastructure/

Deployment, event bus, secrets backend (Vault), and environment
configuration. This is where the *implementation* choices for
cross-cutting concerns designed in `docs/` live — e.g. which event bus
technology backs [010-api-contracts](../docs/010-api-contracts.md)'s event
envelope, and how the Secrets Manager in
[006-integration-hub](../docs/006-integration-hub.md) is backed in each
environment.

Relevant chapters: [001-system-architecture](../docs/001-system-architecture.md),
[009-security](../docs/009-security.md), [010-api-contracts](../docs/010-api-contracts.md)
(open question: event bus technology choice).

Roadmap: Phase 1.
