# The egress relay for a Prime Agent runtime session.
#
#   docker build -t ados-egress-relay:1 infrastructure/prime-runtime/egress-relay
#
# Deliberately minimal. This container is the only network peer a runtime
# container can reach, so its attack surface is part of the runtime's security
# boundary: a stdlib-only Python script, no package manager at run time, no
# shell tooling beyond what the base image carries, non-root, and no ADOS
# credentials of any kind.
#
# The policy is NOT baked in here. It is passed per session as
# ADOS_RELAY_ALLOW, because the allowlist depends on which provider that
# mission was configured with. The image has no default allowlist and refuses
# to start without one — an image that would run "open" if misconfigured is the
# wrong default for the component whose entire job is to be closed.

FROM python:3.12-alpine

# uid 10002: one above the runtime's 10001, and equally not root. Nothing here
# needs privileges — the relay binds high ports only.
RUN addgroup -g 10002 relay && adduser -u 10002 -G relay -D -s /bin/sh relay

COPY --chown=relay:relay relay.py /opt/relay/relay.py

USER relay
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "/opt/relay/relay.py"]
