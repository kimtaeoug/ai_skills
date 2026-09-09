"""Real local-code example; simulated approvals, no model/provider calls.

Exit 1 if the requested test -> rework loop cannot complete. Retain the isolated
workspace so its SQLite state, code artifacts, test logs and receipts are inspectable.
"""
import argparse
import copy
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.claude/skills/task-orchestrator/scripts'))
from graph_runtime import Runtime, encoded
from runtime_contracts import STAGE_SCHEMAS
from task_state import atomic_write


BUGGY = 'def average(values):\n    return sum(values) / len(values)\n'
FIXED = 'def average(values):\n    return sum(values) / len(values) if values else None\n'
CHECKS = '''
import json
import unittest
class AverageChecks(unittest.TestCase):
    def test_positive(self): self.assertEqual(average([2, 4, 6]), 4)
    def test_empty(self): self.assertIsNone(average([]))
    def test_negative(self): self.assertEqual(average([-4, -2]), -3)
    def test_single(self): self.assertEqual(average([7]), 7)
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AverageChecks))
failed = len(result.failures) + len(result.errors)
print(json.dumps(dict(passed=result.testsRun-failed, failed=failed, fatal_errors=0, exit_code=int(not result.wasSuccessful()))))
raise SystemExit(not result.wasSuccessful())
'''


class SimulatedAuthority:
    """Test fixture only: this does NOT authenticate the actual user."""
    def deliver(self, request):
        return True

    def verify(self, proof, request):
        if proof == {'simulation': True, 'digest': request['action_digest']}:
            return 'simulated-owner'


def approve(runtime, state):
    return runtime.approve(state['id'], state['revision'],
                           {'simulation': True, 'digest': state['pending_approval']['action_digest']})


def contract():
    nodes = []
    checks = {
        'develop': [{'validator': 'nonempty_artifact', 'field': 'diff_ref'}],
        'code_test': [{'validator': 'json_success', 'field': 'test_results_ref'},
                      {'validator': 'nonempty_artifact', 'field': 'log_ref'},
                      {'validator': 'equals', 'field': 'exit_code', 'value': 0}],
        'report': [{'validator': 'nonempty_artifact', 'field': 'report_ref'}],
    }
    for ident, kind in [('DEV-01', 'develop'), ('TEST-01', 'code_test'), ('REPORT-01', 'report')]:
        schema = copy.deepcopy(STAGE_SCHEMAS[kind])
        nodes.append({'node_id': ident, 'kind': kind, 'actor': {
            'kind': 'external_system', 'principal_id': 'local-example', 'role': kind},
            'input_schema': schema['input'], 'output_schema': schema['output'],
            'tool_routes': [kind], 'required_evidence': checks[kind]})
    edges = []
    for ident, source, target, trigger in [('EDGE-01', 'DEV-01', 'TEST-01', 'success'),
                                          ('EDGE-02', 'TEST-01', 'REPORT-01', 'success'),
                                          ('LOOP-01', 'TEST-01', 'DEV-01', 'loop')]:
        edges.append({'edge_id': ident, 'from': source, 'to': target, 'trigger': trigger,
                      'guards': ['receipt_valid', 'budget_remaining'], 'required_inputs': [],
                      'required_receipts': [], 'on_missing': 'awaiting_data', 'on_invalid': 'failed'})
    return {'title': 'SIMULATION: average([]) returns None; no UI/research/model',
            'approvers': ['simulated-owner'], 'nodes': nodes, 'edges': edges}


def register(runtime):
    def invoke(kind, inputs, context):
        ident = Path(context['task']).name
        def artifact(data, media='text/plain'):
            return runtime.artifact(ident, data, media)
        if kind == 'develop':
            source = runtime.read_artifact(ident, inputs['work_item_ref'])
            assert source in (BUGGY.encode(), FIXED.encode())
            baseline = runtime.read_artifact(ident, inputs['baseline_ref'])
            diff = ''.join(difflib.unified_diff(baseline.decode().splitlines(True),
                                              source.decode().splitlines(True), 'before.py', 'average.py'))
            outputs = {'diff_ref': artifact(diff.encode()), 'result_refs': [artifact(source, 'text/x-python')],
                       'change_summary_ref': artifact(b'Apply predetermined example implementation; no AI call')}
        elif kind == 'code_test':
            source = runtime.read_artifact(ident, inputs['code_ref'])
            checks = runtime.read_artifact(ident, inputs['test_spec_ref'])
            assert source in (BUGGY.encode(), FIXED.encode()) and checks == CHECKS.encode()
            run = subprocess.run([sys.executable, '-I', '-B', '-'], input=source+b'\n'+checks,
                                 capture_output=True, timeout=10, cwd=context['workspace'])
            result = json.loads(run.stdout)
            assert result['exit_code'] == run.returncode
            outputs = {'test_results_ref': artifact(encoded(result), 'application/json'),
                       'log_ref': artifact(run.stderr), 'exit_code': run.returncode}
        else:
            outputs = {'report_ref': artifact(b'# Average example\n\n4 real Python checks passed. '
                                              b'Approval simulated; no model or UI tests.\n', 'text/markdown')}
        # Known zero: these allowlisted local operations invoke no billable service.
        # This does not account for the surrounding assistant session.
        usage = dict(input_tokens=0, output_tokens=0, other_billable_tokens=0,
                     cost_microusd=0, meter_id='local-no-provider', price_version='no-billable-operation-v1')
        return {'outputs': outputs, 'usage': usage}

    for node in contract()['nodes']:
        kind = node['kind']
        runtime.adapters[kind] = dict(actor=node['actor'], tier=1, bounded=True, cancellable=True,
            idempotent=True, max_tokens=0, max_cost_microusd=0, meter_id='local-no-provider',
            price_version='no-billable-operation-v1',
            allowed=lambda inputs: True, invoke=lambda inputs, ctx, kind=kind: invoke(kind, inputs, ctx))


def outputs(runtime, state, node):
    receipt = json.loads(runtime.read_artifact(state['id'], state['nodes'][node]['receipt']))
    return json.loads(runtime.read_artifact(state['id'], receipt['output_refs'][0]))


def run_case(runtime, source, state=None):
    rework = state is not None
    if state is None:
        state = approve(runtime, runtime.create(contract(), {'max_loop_iterations': 2}))
    ident = state['id']
    ref = lambda text: runtime.artifact(ident, text.encode(), 'text/plain')
    plan = ref('AC-01 normal=4; AC-02 empty=None; AC-03 negative=-3; AC-04 singleton=7. '
               'No UI or research. Predetermined local code; simulated contract approval.')
    state = runtime.execute(ident, 'DEV-01', {'work_item_ref': ref(source),
                            'approved_plan_ref': plan, 'baseline_ref': ref(BUGGY if rework else '')})
    assert state['nodes']['DEV-01']['status'] == 'done', state['reason']
    code = outputs(runtime, state, 'DEV-01')['result_refs'][0]
    prior_usage = state['usage'].copy()
    prior_time = state['clock']['consumed_s']
    if not rework:
        state = approve(runtime, runtime.request_tuning(ident, state['revision'],
                        {'max_loop_iterations': 3}, 'Example workflow-local tuning at idle HIL boundary'))
    assert state['policy_version'] == 2 and state['usage'] == prior_usage
    assert state['clock']['consumed_s'] >= prior_time
    state = runtime.execute(ident, 'TEST-01', {'code_ref': code, 'test_spec_ref': ref(CHECKS)})
    # Read test evidence from the actual attempt, including failed gate evidence.
    attempt = state['attempts'][-1]
    checks = attempt['evidence_results']
    result_ref = next(c['evidence_refs'][0] for c in checks if c['check_id'] == 'test_results_ref')
    result = json.loads(runtime.read_artifact(ident, result_ref))
    log_ref = next(c['evidence_refs'][0] for c in checks if c['check_id'] == 'log_ref')
    return state, {'workflow': ident, 'test': result, 'log': str(runtime.task_path(ident)/log_ref['uri']),
                   'policy_version': state['policy_version'], 'policy_tuning_preserved_usage': True}


def finish_report(runtime, state):
    ident = state['id']
    tested = outputs(runtime, state, 'TEST-01')['test_results_ref']
    state = runtime.execute(ident, 'REPORT-01', {'approved_result_ref': tested,
        'receipt_refs': state['receipts'], 'usage_summary_ref': runtime.artifact(ident, encoded(state['usage']))})
    assert state['status'] == 'completed', state['reason']
    assert runtime.resume(ident)['status'] == 'completed'
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    workspace = Path(tempfile.mkdtemp(prefix='average-workflow-')).resolve()
    subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
    runtime = Runtime(workspace, authority=SimulatedAuthority())
    register(runtime)
    state, result = run_case(runtime, BUGGY)
    assert result['test']['passed'] == 3 and result['test']['failed'] == 1
    assert not state['nodes']['TEST-01']['receipt']
    try:
        state = runtime.loop(state['id'], 'LOOP-01', 'ISSUE-01: average([]) divides by zero; add empty guard')
        loop_error = None
    except ValueError as error:
        loop_error = str(error)
    result.update(status=state['status'], reason=state['reason'], loop_error=loop_error,
                  loop_iterations=state['loop_iterations'], report=str(runtime.report(state['id'])))
    if loop_error is None:
        state, reworked = run_case(runtime, FIXED, state)
        assert reworked['test']['passed'] == 4 and reworked['test']['failed'] == 0
        state = finish_report(runtime, state)
        assert any(a['status'] == 'failed' for a in state['attempts'])
        reworked.update(status=state['status'], loop_iterations=state['loop_iterations'],
                        receipts=len(state['receipts']),
                        attempts=[{'id': a['attempt_id'], 'status': a['status']} for a in state['attempts']],
                        report=str(runtime.report(state['id'])))
    else:
        reworked = None
    # Separate positive control, never a substitute for repairing the failed workflow.
    control, comparison = run_case(runtime, FIXED)
    assert comparison['test']['passed'] == 4 and comparison['test']['failed'] == 0
    control = finish_report(runtime, control)
    comparison.update(status=control['status'], receipts=len(control['receipts']),
                      report=str(runtime.report(control['id'])))
    summary = {'workspace': str(workspace), 'human_approval': 'SIMULATED, not actual user approval',
               'model_calls': 0, 'ui_impact': 'no', 'failing_example': result,
               'same_workflow_rework': reworked,
               'corrected_separate_control': comparison,
               'requested_rework_loop_passed': loop_error is None and state['status'] == 'completed'}
    if args.output:
        # Generated evidence, not another runtime authority. The original SQLite
        # workspace remains at the printed path; these exports are for inspection.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        evidence = args.output.parent / (args.output.stem + '-evidence')
        evidence.mkdir(exist_ok=False)
        for current in (state, control):
            target = evidence / current['id']
            shutil.copytree(runtime.task_path(current['id']), target)
            atomic_write(target / 'state-snapshot.json', json.dumps(runtime.show(current['id']), indent=2))
        summary['evidence_export'] = str(evidence.resolve())
        atomic_write(args.output.resolve(), json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary['requested_rework_loop_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
