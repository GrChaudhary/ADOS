"""
Real persistence for ADOS — replaced the old in-memory + optional-Cloudant
pattern (Cloudant itself has since been removed entirely). See the
ADOS_OBSIDIAN vault TODO ("Database" section) for the phased migration
this belongs to, and the approved plan this was built from.

A sibling package to contracts/, knowledge/, orchestrate/, integrations/
(not nested under backend/app/) because orchestrate/audit_trail.py and
integrations/capability_manifest.py need to import it too — it reaches
across package boundaries to backend.app.config the same way the old
Cloudant client did.
"""
