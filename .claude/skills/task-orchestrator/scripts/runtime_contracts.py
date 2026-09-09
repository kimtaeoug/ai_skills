"""Machine-readable task-orchestrator v2 stage payload contracts.

Approval timestamps are numeric UTC epoch seconds.
"""


def _obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': required or list(properties)}


def _arr(items, min_items=0):
    schema = {'type': 'array', 'items': items}
    if min_items:
        schema['minItems'] = min_items
    return schema


ARTIFACT_REF = _obj({
    'uri': {'type': 'string'},
    'sha256': {'type': 'string'},
    'media_type': {'type': 'string'},
    'bytes': {'type': 'integer', 'minimum': 0},
})

VERSION_BINDING = _obj({
    'workflow_id': {'type': 'string'},
    'contract_version': {'type': 'integer', 'minimum': 0},
    'plan_version': {'type': 'integer', 'minimum': 0},
    'policy_version': {'type': 'integer', 'minimum': 0},
    'input_digest': {'type': 'string'},
    'code_fingerprint': {'type': 'string'},
})

ACTOR = _obj({
    'kind': {'type': 'string', 'enum': ['agent', 'external_system', 'human']},
    'principal_id': {'type': 'string'},
    'role': {'type': 'string'},
})

USAGE = _obj({
    'input_tokens': {'type': 'integer', 'minimum': 0},
    'output_tokens': {'type': 'integer', 'minimum': 0},
    'other_billable_tokens': {'type': 'integer', 'minimum': 0},
    'cost_microusd': {'type': 'integer', 'minimum': 0},
    'meter_id': {'type': 'string'},
    'price_version': {'type': 'string'},
})

APPROVAL = _obj({
    'approval_id': {'type': 'string'},
    'approver_id': {'type': 'string'},
    'action_digest': {'type': 'string'},
    'version_binding': VERSION_BINDING,
    'issued_at': {'type': 'number', 'minimum': 0},
    'expires_at': {'type': 'number', 'minimum': 0},
    'decision': {'type': 'string', 'enum': ['approve', 'deny']},
    'single_use': {'type': 'boolean', 'enum': [True]},
    'auth_evidence_ref': ARTIFACT_REF,
})

COMMON_SCHEMAS = {
    'ArtifactRef': ARTIFACT_REF,
    'Actor': ACTOR,
    'Usage': USAGE,
    'VersionBinding': VERSION_BINDING,
    'Approval': APPROVAL,
}

REFS = _arr(ARTIFACT_REF)

STAGE_SCHEMAS = {
    'contract_hil': {
        'input': _obj({'request_ref': ARTIFACT_REF, 'draft_contract_ref': ARTIFACT_REF}),
        'output': _obj({'approved_contract_ref': ARTIFACT_REF, 'approval': APPROVAL}),
    },
    'strategy': {
        'input': _obj({'approved_contract_ref': ARTIFACT_REF, 'request_ref': ARTIFACT_REF}),
        'output': _obj({'strategy_ref': ARTIFACT_REF, 'research_questions': _arr({'type': 'string'}), 'risk_findings': _arr({'type': 'string'})}),
    },
    'research': {
        'input': _obj({'question': {'type': 'string'}, 'scope_ref': ARTIFACT_REF, 'required': {'type': 'boolean'}}),
        'output': _obj({
            'report_ref': ARTIFACT_REF,
            'claim_verdicts_ref': ARTIFACT_REF,
            'source_refs': REFS,
            'status': {'type': 'string', 'enum': ['answered', 'no-claims-found', 'no-confirmed-claims', 'synthesis-failed']},
        }),
    },
    'plan': {
        'input': _obj({'strategy_ref': ARTIFACT_REF, 'required_research_receipts': REFS}),
        'output': _obj({'dag_ref': ARTIFACT_REF, 'ownership_ref': ARTIFACT_REF, 'acceptance_mapping_ref': ARTIFACT_REF}),
    },
    'plan_hil': {
        'input': _obj({'plan_ref': ARTIFACT_REF, 'contract_ref': ARTIFACT_REF}),
        'output': _obj({'approval': APPROVAL}),
    },
    'develop': {
        'input': _obj({'work_item_ref': ARTIFACT_REF, 'approved_plan_ref': ARTIFACT_REF, 'baseline_ref': ARTIFACT_REF}),
        'output': _obj({'diff_ref': ARTIFACT_REF, 'result_refs': REFS, 'change_summary_ref': ARTIFACT_REF}),
    },
    'code_test': {
        'input': _obj({'code_ref': ARTIFACT_REF, 'test_spec_ref': ARTIFACT_REF}),
        'output': _obj({'test_results_ref': ARTIFACT_REF, 'log_ref': ARTIFACT_REF, 'exit_code': {'type': 'integer'}}),
    },
    'screen_test': {
        'input': _obj({'build_ref': ARTIFACT_REF, 'scenario_ref': ARTIFACT_REF, 'ui_impact': {'type': 'string', 'enum': ['yes', 'unknown']}}),
        'output': _obj({'interaction_results_ref': ARTIFACT_REF, 'screenshots_ref': ARTIFACT_REF, 'trace_ref': ARTIFACT_REF}),
    },
    'visual_review': {
        'input': _obj({'screenshots_ref': ARTIFACT_REF, 'interaction_results_ref': ARTIFACT_REF, 'visual_criteria_ref': ARTIFACT_REF}),
        'output': _obj({'verdicts_ref': ARTIFACT_REF, 'finding_refs': REFS}),
    },
    'evidence_gate': {
        'input': _obj({'producer_output_refs': REFS, 'required_checks_ref': ARTIFACT_REF}),
        'output': _obj({'gate_result': {'type': 'string'}, 'verified_evidence': _arr(ARTIFACT_REF)}),
    },
    'human_approval_gate': {
        'input': _obj({'action_ref': ARTIFACT_REF, 'risk_summary_ref': ARTIFACT_REF, 'approver_policy_ref': ARTIFACT_REF}),
        'output': _obj({'approval': APPROVAL}),
    },
    'final_hil': {
        'input': _obj({'verified_result_ref': ARTIFACT_REF, 'receipt_refs': REFS, 'remaining_risks_ref': ARTIFACT_REF}),
        'output': _obj({'approval': APPROVAL}),
    },
    'report': {
        'input': _obj({'approved_result_ref': ARTIFACT_REF, 'receipt_refs': REFS, 'usage_summary_ref': ARTIFACT_REF}),
        'output': _obj({'report_ref': ARTIFACT_REF}),
    },
}
