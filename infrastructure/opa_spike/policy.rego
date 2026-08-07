package ados.policy_engine

import rego.v1

# Rego re-implementation of integrations/policy_engine.py's two real rules
# (require_governance, hot_disable_policy_rule) for the core-substrate OPA
# spike — same verdicts, different runtime. Not wired into the live
# ConnectorPolicyEngine; see infrastructure/OPA_POLICY_SPIKE.md.

default allow := false

deny contains msg if {
	not input.governance
	msg := "capability call missing required governance context"
}

deny contains msg if {
	input.capability_status == "hot_disabled"
	msg := sprintf("capability %s is hot-disabled", [input.capability])
}

allow if {
	count(deny) == 0
}
