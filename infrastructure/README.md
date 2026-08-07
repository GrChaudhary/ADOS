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
(event bus technology choice — resolved 2026-08-04, see
[EVENT_BUS_COMPARISON.md](EVENT_BUS_COMPARISON.md): real Apache Kafka via
`docker-compose.yml`'s `kafka` service, `EVENT_BUS_BACKEND=kafka`).

Also home to two other core-substrate write-ups from the same session:
[OPA_POLICY_SPIKE.md](OPA_POLICY_SPIKE.md) (proven, not wired in) and
[KEYCLOAK_IDENTITY_DECISION.md](KEYCLOAK_IDENTITY_DECISION.md) (decided,
not built).

Roadmap: Phase 1.
