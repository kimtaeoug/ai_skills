"""Run with python3 tests/test-graph-runtime.py; no real external actions."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / '.claude/skills/task-orchestrator/scripts'
sys.path.insert(0, str(SCRIPTS))


class Authority:
    """Test-only identity provider; production runtime has no permissive default."""
    def deliver(self, request):
        return True

    def verify(self, proof, request):
        return 'owner' if proof == {'test_identity': 'owner', 'digest': request['action_digest']} else None


class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        self.assertTrue((SCRIPTS / 'graph_runtime.py').exists(), 'v2 runtime missing')
        self.m = __import__('graph_runtime')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.workspace)], check=True)
        self.now = 0.0
        self.r = self.m.Runtime(self.workspace, authority=Authority(), now=lambda: self.now)

    def contract(self, routes=None):
        from runtime_contracts import STAGE_SCHEMAS
        schemas = copy.deepcopy(STAGE_SCHEMAS['code_test'])
        schemas['input']['properties']['request'] = {'type': 'string'}
        schemas['input']['required'].append('request')
        schemas['output']['properties']['ok'] = {'type': 'boolean'}
        schemas['output']['required'].append('ok')
        return {'title': 'bounded check', 'approvers': ['owner'], 'nodes': [{
            'node_id': 'TEST-01', 'kind': 'code_test',
            'actor': {'kind': 'external_system', 'principal_id': 'local-check', 'role': 'tester'},
            'input_schema': schemas['input'], 'output_schema': schemas['output'],
            'required_evidence': [{'validator': 'equals', 'field': 'ok', 'value': True},
                                  {'validator': 'json_success', 'field': 'test_results_ref'},
                                  {'validator': 'nonempty_artifact', 'field': 'log_ref'},
                                  {'validator': 'equals', 'field': 'exit_code', 'value': 0}],
            'tool_routes': routes or ['check'], 'timeout_s': 1,
        }], 'edges': []}

    def register(self, invoke=None, **extra):
        call = invoke or (lambda inputs, context: {'outputs': {'ok': True}, 'usage': self.usage()})
        def run(inputs, context):
            result = call(inputs, context)
            if isinstance(result.get('outputs'), dict):
                ident = Path(context['task']).name
                result['outputs'].update(test_results_ref=self.r.artifact(ident, b'{"exit_code":0,"passed":1,"failed":0,"fatal_errors":0}'),
                                         log_ref=self.r.artifact(ident, b'check completed', 'text/plain'), exit_code=0)
            return result
        self.r.adapters['check'] = {
            'actor': self.contract()['nodes'][0]['actor'], 'tier': 1,
            'invoke': run,
            'max_tokens': 10, 'max_cost_microusd': 10,
            'meter_id': 'test-meter', 'price_version': 'fixed-test-price',
            'bounded': True, 'cancellable': True, 'idempotent': True,
            'allowed': lambda inputs: True, **extra}

    def inputs(self, ident, values):
        ref = self.r.artifact(ident, b'fixed approved input')
        return {'code_ref': ref, 'test_spec_ref': ref, **values}

    def execute(self, ident, node_id, inputs):
        return self.r.execute(ident, node_id, self.inputs(ident, inputs))

    def usage(self, tokens=2, cost=3):
        return {'input_tokens': tokens, 'output_tokens': 0, 'other_billable_tokens': 0,
                'cost_microusd': cost, 'meter_id': 'test-meter', 'price_version': 'fixed-test-price'}

    def agree(self, state):
        request = state['pending_approval']
        return self.r.approve(state['id'], state['revision'], {'test_identity': 'owner', 'digest': request['action_digest']})

    def prepared(self, policy=None, contract=None):
        return self.agree(self.r.create(contract or self.contract(), policy or {}))

    def test_unregistered_and_unapproved_calls_do_not_execute(self):
        s = self.r.create(self.contract())
        self.assertEqual(self.execute(s['id'], 'TEST-01', {'request': 'x'})['status'], 'awaiting_data')
        s = self.agree(self.r.show(s['id']))
        self.assertEqual(self.execute(s['id'], 'TEST-01', {'request': 'x'})['status'], 'awaiting_data')
        self.assertEqual(self.r.show(s['id'])['usage']['tokens'], 0)

    def test_receipt_gate_and_resume(self):
        self.register()
        s = self.prepared()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'completed')
        self.assertEqual(out['usage'], {'tokens': 2, 'cost_microusd': 3})
        self.assertEqual(len(out['receipts']), 1)
        self.assertTrue(self.r.read_artifact(out['id'], out['receipts'][0]))
        self.assertEqual(self.r.resume(s['id'])['status'], 'completed')

    def test_missing_and_invalid_inputs_take_different_edges(self):
        self.register()
        s = self.prepared()
        missing = self.execute(s['id'], 'TEST-01', {})
        self.assertEqual(missing['status'], 'awaiting_data')
        invalid = self.execute(s['id'], 'TEST-01', {'request': 9})
        self.assertEqual(invalid['status'], 'failed')
        self.assertEqual(invalid['attempts'][-1]['status'], 'failed')

    def test_evidence_failure_never_commits_receipt(self):
        self.register(lambda inputs, ctx: {'outputs': {'ok': False}, 'usage': self.usage()})
        s = self.prepared()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertNotEqual(out['status'], 'completed')
        self.assertEqual(out['receipts'], [])

    def test_failed_test_waits_without_rework_edge_and_cannot_retry_blindly(self):
        self.register(lambda inputs, ctx: {'outputs': {'ok': False}, 'usage': self.usage()})
        contract = self.contract()
        contract['edges'] = [self.edge('retry')]
        s = self.prepared(contract=contract)
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(out['attempts'][0]['status'], 'failed')
        self.assertIsNone(out['nodes']['TEST-01']['receipt'])
        self.register()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(len(out['attempts']), 1)

    def test_failed_test_reworks_with_new_inputs_preserving_failure_and_usage(self):
        self.register(lambda inputs, ctx: {'outputs': {'ok': False}, 'usage': self.usage()})
        contract = self.contract()
        contract['edges'] = [self.edge('loop')]
        s = self.prepared(contract=contract)
        out = self.execute(s['id'], 'TEST-01', {'request': 'buggy'})
        self.assertEqual(out['status'], 'ready')
        out = self.r.loop(s['id'], 'EDGE-01', 'fix the tested defect')
        self.assertEqual(out['usage']['tokens'], 2)
        self.assertEqual(out['attempts'][0]['status'], 'failed')
        self.register()
        out = self.execute(s['id'], 'TEST-01', {'request': 'fixed'})
        self.assertEqual(out['status'], 'completed')
        self.assertEqual([a['status'] for a in out['attempts']], ['failed', 'done'])
        self.assertEqual(out['usage']['tokens'], 4)
        self.assertEqual(out['loop_iterations'], 1)
        self.assertEqual(len(out['receipts']), 1)

    def test_rework_cannot_escape_limits_or_safety_failures(self):
        contract = self.contract()
        contract['edges'] = [self.edge('loop')]
        for mode in ('loop_cap', 'time_cap', 'reservation_violation', 'policy_denied', 'approval_denied'):
            with self.subTest(mode=mode):
                self.register(lambda inputs, ctx: {'outputs': {'ok': False}, 'usage': self.usage()})
                policy = {'max_loop_iterations': 0} if mode == 'loop_cap' else {}
                if mode == 'reservation_violation':
                    self.register(max_tokens=1)
                if mode == 'policy_denied':
                    self.register(allowed=lambda inputs: False)
                if mode == 'approval_denied':
                    self.register(tier=3)
                s = self.prepared(policy=policy, contract=contract)
                out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
                if mode == 'approval_denied':
                    out = self.r.deny(out['id'], out['revision'], {'test_identity': 'owner', 'digest': out['pending_approval']['action_digest']})
                if mode == 'time_cap':
                    self.now += 3601
                if mode in ('loop_cap', 'time_cap'):
                    out = self.r.loop(s['id'], 'EDGE-01', 'must respect limits')
                    self.assertEqual(out['status'], 'failed')
                with self.assertRaises(ValueError):
                    self.r.loop(s['id'], 'EDGE-01', 'must not revive terminal failure')

    def test_rework_authorization_survives_tier_three_approval_wait(self):
        self.register(lambda inputs, ctx: {'outputs': {'ok': False}, 'usage': self.usage()}, tier=3)
        contract = self.contract()
        contract['edges'] = [self.edge('loop')]
        s = self.prepared(contract=contract)
        out = self.execute(s['id'], 'TEST-01', {'request': 'buggy'})
        self.agree(out)
        out = self.execute(s['id'], 'TEST-01', {'request': 'buggy'})
        self.assertEqual(out['attempts'][0]['status'], 'failed')
        self.r.loop(s['id'], 'EDGE-01', 'repair requires a fresh action approval')
        self.register(tier=3)
        out = self.execute(s['id'], 'TEST-01', {'request': 'fixed'})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(len(out['attempts']), 1)
        self.agree(out)
        out = self.execute(s['id'], 'TEST-01', {'request': 'fixed'})
        self.assertEqual(out['status'], 'completed')
        self.assertEqual([a['status'] for a in out['attempts']], ['failed', 'done'])
        self.assertNotEqual(out['attempts'][0]['approval_id'], out['attempts'][1]['approval_id'])

    def test_hil_wait_excluded_and_tuning_preserves_consumption(self):
        # Long HIL is independent of the deliberately extended approval lifetime.
        s = self.prepared({'approval_timeout_s': 10000})
        self.now = 600
        s = self.r.request_tuning(s['id'], s['revision'], {'max_tokens': 200000}, 'measured need')
        self.now = 7800
        s = self.agree(s)
        self.assertEqual(s['clock']['consumed_s'], 600)
        self.assertEqual(s['policy']['max_tokens'], 200000)
        self.assertEqual(s['policy_version'], 2)
        self.assertEqual(s['policy_history'][-1]['reason'], 'measured need')

    def test_no_identity_adapter_cannot_pause_clock_or_approve(self):
        self.r.authority = None
        s = self.r.create(self.contract())
        self.now = 3601
        out = self.r.resume(s['id'])
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['reason'], 'workflow_timeout')

    def test_approval_expiration_and_replay(self):
        s = self.r.create(self.contract())
        self.now = 601
        out = self.r.approve(s['id'], s['revision'], {'test_identity': 'owner', 'digest': s['pending_approval']['action_digest']})
        self.assertNotEqual(out['status'], 'ready')
        self.assertEqual(out['clock']['consumed_s'], 0)
        self.assertIn('expired', out['reason'])

    def test_unknown_usage_keeps_reservation_and_stops(self):
        self.register(lambda inputs, ctx: {'outputs': {'ok': True}, 'usage': None})
        s = self.prepared()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(sum(x['tokens'] for x in out['reservations'].values()), 10)
        self.assertEqual(len(self.execute(s['id'], 'TEST-01', {'request': 'x'})['attempts']), 1)

    def test_budget_rejected_before_call(self):
        self.register()
        s = self.prepared({'max_tokens': 1})
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['reason'], 'budget_exhausted')
        self.assertEqual(out['reservations'], {})

    def test_tier_three_requires_bound_single_use_approval(self):
        self.register(tier=3, idempotent=False)
        s = self.prepared()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'awaiting_data')
        out = self.agree(out)
        done = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(done['status'], 'completed')
        self.assertTrue(done['attempts'][0]['intent'])

    def test_artifact_mutation_blocks_resume(self):
        self.register()
        s = self.prepared()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        path = self.r.task_path(s['id']) / out['receipts'][0]['uri']
        path.write_bytes(b'corrupted')
        self.assertEqual(self.r.resume(s['id'])['status'], 'awaiting_data')

    def edge(self, trigger='retry', source='TEST-01', target='TEST-01'):
        return {'edge_id': 'EDGE-01', 'from': source, 'to': target, 'trigger': trigger,
                'guards': ['receipt_valid', 'budget_remaining', 'same_inputs'],
                'required_inputs': ['request'], 'required_receipts': [],
                'on_missing': 'awaiting_data', 'on_invalid': 'failed'}

    def test_retry_records_failure_and_preserves_budget(self):
        self.register(lambda inputs, ctx: {'error': 'service_unavailable', 'usage': self.usage()})
        contract = self.contract()
        contract['edges'] = [self.edge()]
        s = self.prepared({'retry': {'base_delay_s': 0, 'cap_delay_s': 0}}, contract)
        for index in range(3):
            out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['usage']['tokens'], 6)
        self.assertEqual([a['status'] for a in out['attempts']], ['failed'] * 3)
        self.assertEqual(out['tool_retries'], 2)

    def test_fallback_uses_explicit_edge_and_same_attempt_budget(self):
        self.register(lambda inputs, ctx: {'error': 'service_unavailable', 'usage': self.usage()})
        backup = copy.copy(self.r.adapters['check'])
        self.register()
        backup['invoke'] = self.r.adapters['check']['invoke']
        self.r.adapters['check']['invoke'] = lambda inputs, ctx: {'error': 'service_unavailable', 'usage': self.usage()}
        self.r.adapters['backup'] = backup
        contract = self.contract(['check', 'backup'])
        contract['edges'] = [self.edge('fallback')]
        s = self.prepared({'retry': {'base_delay_s': 0, 'cap_delay_s': 0}}, contract)
        self.execute(s['id'], 'TEST-01', {'request': 'x'})
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'completed')
        self.assertEqual([a['route'] for a in out['attempts']], ['check', 'backup'])

    def test_changed_retry_inputs_are_rejected(self):
        self.register(lambda inputs, ctx: {'error': 'service_unavailable', 'usage': self.usage()})
        contract = self.contract()
        contract['edges'] = [self.edge()]
        s = self.prepared({'retry': {'base_delay_s': 0, 'cap_delay_s': 0}}, contract)
        self.execute(s['id'], 'TEST-01', {'request': 'x'})
        out = self.execute(s['id'], 'TEST-01', {'request': 'changed'})
        self.assertEqual(len(out['attempts']), 1)
        self.assertEqual(out['reason'], 'retry_inputs_changed')

    def test_unknown_result_reconciles_without_reinvocation(self):
        self.register(lambda inputs, ctx: {'outputs': {'ok': True}, 'usage': None})
        original = self.r.adapters['check']
        self.register()
        original['reconcile'] = self.r.adapters['check']['invoke']
        self.r.adapters['check'] = original
        s = self.prepared()
        self.execute(s['id'], 'TEST-01', {'request': 'x'})
        out = self.r.reconcile(s['id'], 'TEST-01')
        self.assertEqual(out['status'], 'completed')
        self.assertEqual(len(out['attempts']), 1)
        self.assertEqual(out['reservations'], {})

    def test_tool_timeout_keeps_unconfirmed_usage_reserved(self):
        self.register(lambda inputs, ctx: (time.sleep(1), {'outputs': {'ok': True}, 'usage': self.usage()})[1])
        contract = self.contract()
        contract['nodes'][0]['timeout_s'] = 0.05
        s = self.prepared(contract=contract)
        start = time.monotonic()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertLess(time.monotonic() - start, 0.8)
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertTrue(out['reservations'])

    def test_loop_edge_cap_and_receipt_invalidation(self):
        self.register()
        contract = self.contract()
        contract['edges'] = [self.edge('loop')]
        second = copy.deepcopy(contract['nodes'][0])
        second['node_id'] = 'TEST-02'
        contract['nodes'].append(second)
        s = self.prepared({'max_loop_iterations': 1}, contract)
        self.execute(s['id'], 'TEST-01', {'request': 'x'})
        out = self.r.loop(s['id'], 'EDGE-01', 'additional verification')
        self.assertEqual(out['nodes']['TEST-01']['status'], 'pending')
        self.assertEqual(out['nodes']['TEST-01']['receipt'], None)
        self.assertEqual(out['nodes']['TEST-01']['attempts'], 1)
        out = self.r.loop(s['id'], 'EDGE-01', 'again')
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['reason'], 'loop_budget_exhausted')

    def test_tuning_lower_cap_than_spend_stops_without_reset(self):
        self.register()
        contract = self.contract()
        second = copy.deepcopy(contract['nodes'][0])
        second['node_id'] = 'TEST-02'
        contract['nodes'].append(second)
        contract['edges'] = [self.edge('success', target='TEST-02')]
        s = self.prepared(contract=contract)
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        out = self.r.request_tuning(s['id'], out['revision'], {'max_tokens': 1}, 'lower user limit')
        out = self.agree(out)
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['usage']['tokens'], 2)

    def test_forged_approval_does_not_mutate_state(self):
        s = self.r.create(self.contract())
        with self.assertRaises(ValueError):
            self.r.approve(s['id'], s['revision'], {'test_identity': 'attacker'})
        self.assertEqual(self.r.show(s['id']), s)

    def test_success_cannot_override_concurrent_terminal_failure(self):
        self.register()
        s = self.prepared()
        with self.r.connection() as db:
            state = self.r.load(db, s['id'])
            attempt, adapter = self.r.before_tool_call(db, state, 'TEST-01', self.inputs(s['id'], {'request': 'x'}))
            state.update(status='failed', reason='safety_stop')
            self.r.settle(db, state, attempt, adapter, {'outputs': {'ok': True}, 'usage': self.usage()})
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['reason'], 'safety_stop')
            self.assertEqual(state['receipts'], [])

    def test_completed_workflow_has_derived_report_artifact(self):
        self.register()
        s = self.prepared()
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertIn(b'TEST-01', self.r.read_artifact(s['id'], out['report_ref']))

    def test_stale_code_blocks_next_edge(self):
        self.register()
        contract = self.contract()
        second = copy.deepcopy(contract['nodes'][0])
        second['node_id'] = 'TEST-02'
        contract['nodes'].append(second)
        contract['edges'] = [self.edge('success', target='TEST-02')]
        s = self.prepared(contract=contract)
        self.execute(s['id'], 'TEST-01', {'request': 'x'})
        (self.workspace / 'changed.txt').write_text('after tests')
        out = self.execute(s['id'], 'TEST-02', {'request': 'x'})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(len(out['attempts']), 1)

    def test_nested_artifact_reference_verified_at_input_boundary(self):
        self.register()
        contract = self.contract()
        contract['nodes'][0]['input_schema']['properties']['request'] = self.m.ARTIFACT_SCHEMA
        s = self.prepared(contract=contract)
        ref = self.r.artifact(s['id'], b'test')
        (self.r.task_path(s['id']) / ref['uri']).write_bytes(b'tampered')
        out = self.execute(s['id'], 'TEST-01', {'request': ref})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(out['attempts'], [])

    def test_declared_same_inputs_guard_blocks_changed_downstream(self):
        self.register()
        contract = self.contract()
        second = copy.deepcopy(contract['nodes'][0])
        second['node_id'] = 'TEST-02'
        contract['nodes'].append(second)
        contract['edges'] = [self.edge('success', target='TEST-02')]
        s = self.prepared(contract=contract)
        self.execute(s['id'], 'TEST-01', {'request': 'original'})
        out = self.execute(s['id'], 'TEST-02', {'request': 'changed'})
        self.assertEqual(len(out['attempts']), 1)
        self.assertEqual(out['status'], 'failed')

    def test_missing_primary_cannot_be_hidden_by_fallback(self):
        self.register()
        self.r.adapters['backup'] = self.r.adapters.pop('check')
        contract = self.contract(['check', 'backup'])
        contract['edges'] = [self.edge('fallback')]
        s = self.prepared(contract=contract)
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'awaiting_data')
        self.assertEqual(out['attempts'], [])

    def test_malformed_enum_and_unknown_quality_field_rejected(self):
        contract = self.contract()
        contract['nodes'][0]['input_schema']['properties']['request']['enum'] = 'abc'
        with self.assertRaises(ValueError):
            self.r.create(contract)
        contract = self.contract()
        contract['nodes'][0]['quality_policy'] = {'field': 'score', 'minimum': 0.8, 'evaluator_id': 'score-v1', 'evaluator_version': '1'}
        with self.assertRaises(ValueError):
            self.r.create(contract)

    def test_approval_receipt_has_verifiable_authority_evidence(self):
        s = self.prepared()
        approval = s['approvals'][0]
        self.assertEqual(approval['decision'], 'approve')
        self.assertIs(approval['single_use'], True)
        self.assertTrue(self.r.read_artifact(s['id'], approval['auth_evidence_ref']))

    def test_stage_contract_cannot_omit_canonical_required_payload(self):
        contract = self.contract()
        contract['nodes'][0]['input_schema'] = {'type': 'object', 'properties': {'request': {'type': 'string'}}}
        with self.assertRaises(ValueError):
            self.r.create(contract)

    def test_approval_attestation_tampering_blocks_resume(self):
        s = self.prepared()
        ref = s['approvals'][0]['auth_evidence_ref']
        (self.r.task_path(s['id']) / ref['uri']).write_bytes(b'corrupted')
        self.assertEqual(self.r.resume(s['id'])['status'], 'awaiting_data')

    def test_parallel_work_prevents_global_hil_clock_pause(self):
        self.register(tier=3)
        contract = self.contract()
        second = copy.deepcopy(contract['nodes'][0])
        second.update(node_id='TEST-02', tool_routes=['background'])
        contract['nodes'].append(second)
        self.r.adapters['background'] = {**self.r.adapters['check'], 'tier': 1}
        s = self.prepared(contract=contract)
        with self.r.connection() as db:
            state = self.r.load(db, s['id'])
            background, adapter = self.r.before_tool_call(db, state, 'TEST-02', self.inputs(s['id'], {'request': 'x'}))
            self.r.before_tool_call(db, state, 'TEST-01', self.inputs(s['id'], {'request': 'x'}))
            self.now = 100
            self.r.account(state)
            self.assertEqual(state['clock']['consumed_s'], 100)
            self.assertEqual(state['nodes']['TEST-01']['clock']['consumed_s'], 0)
            self.assertEqual(state['nodes']['TEST-02']['clock']['consumed_s'], 100)

    def test_deadline_recovery_allows_query_not_duplicate_execution(self):
        self.register()
        s = self.prepared()
        with self.r.connection() as db:
            state = self.r.load(db, s['id'])
            self.r.before_tool_call(db, state, 'TEST-01', self.inputs(s['id'], {'request': 'x'}))
            self.r.save(db, state, 'simulated_supervisor_loss')
        self.now = 2
        state = self.r.resume(s['id'])
        self.assertEqual(state['attempts'][0]['status'], 'unknown')
        self.assertTrue(state['reservations'])

    def test_invalid_tier_boolean_does_not_downgrade_risk(self):
        self.register(tier=True)
        s = self.prepared()
        state = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['attempts'], [])

    def test_live_clock_uses_monotonic_elapsed_time(self):
        with patch.object(self.m.time, 'time', return_value=1000), patch.object(self.m.time, 'monotonic', side_effect=[5, 15]):
            runtime = self.m.Runtime(self.workspace)
            self.assertEqual(runtime.now(), 1010)

    def test_supervisor_cancels_on_terminal_policy_signal(self):
        start = time.monotonic()
        out = self.m.bounded_call(lambda inputs, ctx: time.sleep(1), {}, {}, 2, cancelled=lambda: True)
        self.assertEqual(out['error'], 'policy_cancelled')
        self.assertLess(time.monotonic() - start, 0.8)

    def test_authentication_failure_is_not_retried_or_counted_as_outage(self):
        self.register(lambda inputs, ctx: {'error': 'authentication_failed', 'usage': self.usage()})
        contract = self.contract()
        contract['edges'] = [self.edge()]
        s = self.prepared(contract=contract)
        out = self.execute(s['id'], 'TEST-01', {'request': 'x'})
        self.assertEqual(out['status'], 'failed')
        with self.r.connection() as db:
            self.assertIsNone(db.execute('SELECT failures FROM breakers WHERE route=?', ('check',)).fetchone())

    def test_test_evidence_booleans_are_not_exit_codes(self):
        s = self.prepared()
        ref = self.r.artifact(s['id'], b'{"exit_code":false,"passed":1,"failed":0,"fatal_errors":0}')
        outputs = {'ok': True, 'test_results_ref': ref, 'log_ref': self.r.artifact(s['id'], b'log'), 'exit_code': 0}
        results = self.r.evidence(s['id'], self.contract()['nodes'][0], outputs)
        self.assertEqual(next(x['status'] for x in results if x['check_id'] == 'test_results_ref'), 'fail')


if __name__ == '__main__':
    unittest.main()
