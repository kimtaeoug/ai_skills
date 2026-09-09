"""Run with python3 tests/test-runtime-contracts.py."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / '.claude/skills/task-orchestrator/scripts'
sys.path.insert(0, str(SCRIPTS))

import graph_runtime
import runtime_contracts


REF = {
    'uri': 'artifacts/' + 'a' * 64,
    'sha256': 'a' * 64,
    'media_type': 'application/json',
    'bytes': 2,
}

APPROVAL = {
    'approval_id': 'approval-1',
    'approver_id': 'owner',
    'action_digest': 'digest',
    'version_binding': {
        'workflow_id': 'WF-0001',
        'contract_version': 1,
        'plan_version': 1,
        'policy_version': 1,
        'input_digest': 'input',
        'code_fingerprint': 'code',
    },
    'issued_at': 1788883200,
    'expires_at': 1788883800,
    'decision': 'approve',
    'single_use': True,
    'auth_evidence_ref': REF,
}


def valid_payload(schema):
    kind = schema['type']
    if kind == 'object':
        return {name: valid_payload(child) for name, child in schema['properties'].items()}
    if kind == 'array':
        return [valid_payload(schema['items'])] if schema.get('minItems', 0) else []
    if kind == 'string':
        return schema.get('enum', ['x'])[0]
    if kind == 'integer':
        return schema.get('minimum', 0)
    if kind == 'number':
        return schema.get('minimum', 0)
    if kind == 'boolean':
        return True
    raise AssertionError(kind)


class RuntimeContracts(unittest.TestCase):
    def test_all_exported_stage_schemas_are_graph_runtime_schemas(self):
        self.assertEqual(
            set(runtime_contracts.STAGE_SCHEMAS),
            {
                'contract_hil', 'strategy', 'research', 'plan', 'plan_hil',
                'develop', 'code_test', 'screen_test', 'visual_review',
                'evidence_gate', 'human_approval_gate', 'final_hil', 'report',
            },
        )
        for contract in runtime_contracts.STAGE_SCHEMAS.values():
            graph_runtime.validate_schema(contract['input'])
            graph_runtime.validate_schema(contract['output'])
            self.assertEqual(graph_runtime.schema_check(valid_payload(contract['input']), contract['input'])[0], 'pass')
            self.assertEqual(graph_runtime.schema_check(valid_payload(contract['output']), contract['output'])[0], 'pass')

    def test_stage_payloads_reject_missing_wrong_and_extra_fields(self):
        for stage, contract in runtime_contracts.STAGE_SCHEMAS.items():
            for direction, schema in contract.items():
                with self.subTest(stage=stage, direction=direction):
                    payload = valid_payload(schema)
                    first = schema['required'][0]

                    missing = dict(payload)
                    del missing[first]
                    self.assertEqual(graph_runtime.schema_check(missing, schema)[0], 'missing')

                    wrong = dict(payload)
                    wrong[first] = 'wrong' if schema['properties'][first]['type'] != 'string' else 0
                    self.assertEqual(graph_runtime.schema_check(wrong, schema)[0], 'invalid')

                    extra = dict(payload, debug=True)
                    self.assertEqual(graph_runtime.schema_check(extra, schema)[0], 'invalid')

    def test_common_reference_metadata_is_closed_and_required(self):
        schema = runtime_contracts.COMMON_SCHEMAS['ArtifactRef']
        self.assertEqual(graph_runtime.schema_check(REF, schema)[0], 'pass')

        missing = dict(REF)
        del missing['sha256']
        self.assertEqual(graph_runtime.schema_check(missing, schema)[0], 'missing')

        wrong = dict(REF, bytes=-1)
        self.assertEqual(graph_runtime.schema_check(wrong, schema)[0], 'invalid')

        extra = dict(REF, mutable=True)
        self.assertEqual(graph_runtime.schema_check(extra, schema)[0], 'invalid')

    def test_human_approval_outputs_require_authenticated_runtime_record_fields(self):
        schema = runtime_contracts.STAGE_SCHEMAS['human_approval_gate']['output']
        self.assertEqual(graph_runtime.schema_check({'approval': APPROVAL}, schema)[0], 'pass')

        forged = {'approval': dict(APPROVAL, single_use=False)}
        self.assertEqual(graph_runtime.schema_check(forged, schema)[0], 'invalid')

        missing_policy = {'approval': dict(APPROVAL, version_binding={
            'workflow_id': 'WF-0001',
            'contract_version': 1,
            'plan_version': 1,
            'input_digest': 'input',
            'code_fingerprint': 'code',
        })}
        self.assertEqual(graph_runtime.schema_check(missing_policy, schema)[0], 'missing')

        iso_time = {'approval': dict(APPROVAL, issued_at='2026-09-09T00:00:00Z')}
        self.assertEqual(graph_runtime.schema_check(iso_time, schema)[0], 'invalid')


if __name__ == '__main__':
    unittest.main()
