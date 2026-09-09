#!/usr/bin/env python3
"""Real-process reliability/load probe for task-orchestrator v2 graph_runtime."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.claude/skills/task-orchestrator/scripts'
RUNTIME_SCRIPT = SCRIPTS / 'graph_runtime.py'
ENV = {key: os.environ[key] for key in ('PATH', 'TMPDIR', 'SYSTEMROOT') if key in os.environ}
ENV.update(PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)


def load_runtime():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('graph_runtime', RUNTIME_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GRAPH = load_runtime()


class Authority:
    def deliver(self, request):
        return True

    def verify(self, proof, request):
        if proof == {'test_identity': 'owner', 'digest': request['action_digest']}:
            return 'owner'
        return None


def usage(tokens=2, cost=3):
    return {'input_tokens': tokens, 'output_tokens': 0, 'other_billable_tokens': 0,
            'cost_microusd': cost, 'meter_id': 'probe-meter', 'price_version': 'fixed-probe-price'}


def node(node_id, routes=None):
    artifact = GRAPH.ARTIFACT_SCHEMA
    return {
        'node_id': node_id, 'kind': 'code_test',
        'actor': {'kind': 'external_system', 'principal_id': 'local-probe', 'role': 'tester'},
        'input_schema': {
            'type': 'object',
            'properties': {'code_ref': artifact, 'test_spec_ref': artifact, 'request': {'type': 'string'}},
            'required': ['code_ref', 'test_spec_ref'],
        },
        'output_schema': {
            'type': 'object',
            'properties': {
                'test_results_ref': artifact,
                'log_ref': artifact,
                'exit_code': {'type': 'integer'},
                'ok': {'type': 'boolean'},
            },
            'required': ['test_results_ref', 'log_ref', 'exit_code'],
        },
        'required_evidence': [
            {'validator': 'json_success', 'field': 'test_results_ref'},
            {'validator': 'nonempty_artifact', 'field': 'log_ref'},
            {'validator': 'equals', 'field': 'exit_code', 'value': 0},
            {'validator': 'equals', 'field': 'ok', 'value': True},
        ],
        'tool_routes': routes or ['check'], 'timeout_s': 5,
    }


def contract(count=1):
    return {'title': 'runtime probe', 'approvers': ['owner'],
            'nodes': [node(f'TEST-{index + 1:02d}') for index in range(count)], 'edges': []}


def workspace(root, name):
    path = root / name
    path.mkdir()
    subprocess.run(['git', 'init', '-q', str(path)], check=True, env=ENV)
    (path / 'fixture.txt').write_text('probe\n')
    return path


def approve(runtime, state):
    request = state['pending_approval']
    return runtime.approve(state['id'], state['revision'],
                           {'test_identity': 'owner', 'digest': request['action_digest']})


def runtime_with_adapter(workspace_path, log_path=None, result='success', sleep_s=0.0, now=None):
    runtime = GRAPH.Runtime(workspace_path, authority=Authority(), now=now)

    def invoke(inputs, context):
        if log_path:
            with open(log_path, 'a') as handle:
                handle.write(json.dumps({'pid': os.getpid(), 'intent': context.get('intent'),
                                         'input': inputs, 'at': time.time()}) + '\n')
        if sleep_s:
            time.sleep(sleep_s)
        if result == 'error':
            return {'error': 'service_unavailable', 'usage': usage()}
        if result == 'unknown':
            return {'outputs': {'ok': True}, 'usage': None}
        ident = Path(context['task']).name
        result_ref = runtime.artifact(ident, json.dumps(
            {'passed': 1, 'failed': 0, 'fatal_errors': 0, 'exit_code': 0},
            sort_keys=True).encode())
        log_ref = runtime.artifact(ident, b'probe log: passed\n', 'text/plain')
        return {'outputs': {'test_results_ref': result_ref, 'log_ref': log_ref, 'exit_code': 0, 'ok': True},
                'usage': usage()}

    runtime.adapters['check'] = {
        'actor': node('TEST-01')['actor'], 'tier': 1, 'invoke': invoke,
        'max_tokens': 10, 'max_cost_microusd': 10,
        'meter_id': 'probe-meter', 'price_version': 'fixed-probe-price',
        'bounded': True, 'cancellable': True, 'idempotent': True,
        'allowed': lambda inputs: True,
    }
    return runtime


def create_ready(workspace_path, contract_value=None, policy=None, now=None):
    runtime = runtime_with_adapter(workspace_path, now=(lambda: now) if now is not None else None)
    state = approve(runtime, runtime.create(contract_value or contract(), policy or {}))
    return state['id']


def input_refs(runtime, workflow_id, node_id):
    return {
        'code_ref': runtime.artifact(workflow_id, f'code for {node_id}\n'.encode(), 'text/plain'),
        'test_spec_ref': runtime.artifact(workflow_id, f'spec for {node_id}\n'.encode(), 'text/plain'),
        'request': node_id,
    }


def child_execute(workspace_path, workflow_id, node_id, log_path, result='success', sleep_s=0.0, now=None):
    runtime = runtime_with_adapter(workspace_path, log_path, result, sleep_s, now=(lambda: now) if now is not None else None)
    started = time.perf_counter()
    try:
        state = runtime.execute(workflow_id, node_id, input_refs(runtime, workflow_id, node_id))
        return {'ok': True, 'status': state['status'], 'reason': state['reason'],
                'receipts': len(state['receipts']), 'reservations': len(state['reservations']),
                'ms': (time.perf_counter() - started) * 1000}
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'ms': (time.perf_counter() - started) * 1000}


def lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def classify(name, passed, **details):
    return {'name': name, 'pass': bool(passed), **details}


def percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, int((len(values) - 1) * pct / 100))
    return values[index]


def show_once(args):
    workspace_path, workflow_id = args
    runtime = GRAPH.Runtime(workspace_path, authority=Authority())
    start = time.perf_counter()
    runtime.show(workflow_id)
    return (time.perf_counter() - start) * 1000


def probe_show_load(root):
    repo = workspace(root, 'show-load')
    runtime = runtime_with_adapter(repo)
    ids = [approve(runtime, runtime.create(contract()))['id'] for _ in range(300)]
    rows = []
    for workers in (1, 4, 8):
        calls = [(str(repo), random.choice(ids)) for _ in range(48)]
        start = time.perf_counter()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            samples = list(pool.map(show_once, calls))
        elapsed = time.perf_counter() - start
        rows.append({'processes': workers, 'calls': len(samples),
                     'ops_per_second': len(samples) / elapsed,
                     'p50_ms': statistics.median(samples),
                     'p95_ms': percentile(samples, 95),
                     'max_ms': max(samples)})
    return classify('show load over 300 workflows', all(row['p95_ms'] < 2000 for row in rows),
                    fixture_workflows=300, threshold_p95_ms=2000, rows=rows)


def probe_same_node(root):
    repo = workspace(root, 'same-node')
    log = root / 'same-node.jsonl'
    workflow_id = create_ready(repo)
    with ProcessPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(child_execute, [str(repo)] * 48, [workflow_id] * 48,
                             ['TEST-01'] * 48, [str(log)] * 48, ['success'] * 48, [0.2] * 48))
    final = runtime_with_adapter(repo).show(workflow_id)
    invokes = lines(log)
    unexpected_errors = [row for row in rows if not row['ok']]
    return classify('simultaneous same-node execute commits exactly one receipt',
                    not unexpected_errors and len(invokes) == 1
                    and len(final['receipts']) == 1 and final['usage']['tokens'] == 2,
                    calls=48, child_results=rows, invocation_count=len(invokes),
                    unexpected_child_errors=unexpected_errors,
                    receipt_count=len(final['receipts']), usage=final['usage'],
                    final_status=final['status'], final_reason=final['reason'])


def probe_distinct_caps(root):
    repo = workspace(root, 'distinct-caps')
    log = root / 'distinct-caps.jsonl'
    workflow_id = create_ready(repo, contract(8), {'max_tokens': 40, 'max_cost_microusd': 40})
    node_ids = [f'TEST-{index + 1:02d}' for index in range(8)]
    with ProcessPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(child_execute, [str(repo)] * 8, [workflow_id] * 8,
                             node_ids, [str(log)] * 8, ['success'] * 8, [0.4] * 8))
    final = runtime_with_adapter(repo).show(workflow_id)
    invokes = lines(log)
    running_or_done = sum(1 for n in final['nodes'].values() if n['status'] in ('running', 'done'))
    committed_plus_reserved = len(final['receipts']) + len(final['reservations'])
    unexpected_errors = [row for row in rows if not row['ok']]
    return classify('parallel distinct-node reservations do not exceed caps',
                    not unexpected_errors and 0 < len(invokes) <= 4 and final['usage']['tokens'] <= 8
                    and running_or_done <= 4 and committed_plus_reserved <= 4,
                    contenders=8, token_cap=40, route_max_tokens=10,
                    invocation_count=len(invokes), running_or_done=running_or_done,
                    committed_plus_reserved=committed_plus_reserved,
                    unexpected_child_errors=unexpected_errors,
                    child_results=rows, usage=final['usage'], reservations=final['reservations'],
                    final_status=final['status'], final_reason=final['reason'])


def open_breaker(repo):
    for index in range(3):
        workflow_id = create_ready(repo, policy={'breaker': {'failure_threshold': 3, 'cooldown_s': 1}}, now=float(index))
        child_execute(str(repo), workflow_id, 'TEST-01', None, result='error', now=float(index))


def probe_breaker_half_open(root):
    repo = workspace(root, 'breaker-half-open')
    log = root / 'breaker-half-open.jsonl'
    open_breaker(repo)
    ids = [create_ready(repo, policy={'breaker': {'failure_threshold': 3, 'cooldown_s': 1}}, now=5.0) for _ in range(8)]
    with ProcessPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(child_execute, [str(repo)] * 8, ids, ['TEST-01'] * 8,
                             [str(log)] * 8, ['success'] * 8, [0.25] * 8, [5.0] * 8))
    unexpected_errors = [row for row in rows if not row['ok']]
    return classify('workspace breaker half-open allows a single probe across workflows',
                    not unexpected_errors and len(lines(log)) == 1,
                    workflows=8, invocation_count=len(lines(log)),
                    unexpected_child_errors=unexpected_errors, child_results=rows)


def crash_child(workspace_path, workflow_id, mode, log_path):
    code = textwrap.dedent("""
        import importlib.util, json, os, pathlib, sys, time
        scripts = pathlib.Path(os.environ['SCRIPTS'])
        sys.path.insert(0, str(scripts))
        spec = importlib.util.spec_from_file_location('graph_runtime', scripts / 'graph_runtime.py')
        graph = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(graph)
        class Authority:
            def deliver(self, request): return True
            def verify(self, proof, request): return 'owner' if proof == {'test_identity': 'owner', 'digest': request['action_digest']} else None
        def invoke(inputs, context):
            with open(os.environ['LOG'], 'a') as handle:
                handle.write(json.dumps({'pid': os.getpid(), 'mode': os.environ['MODE']}) + '\\n')
            ident = pathlib.Path(context['task']).name
            result_ref = runtime.artifact(ident, json.dumps({'passed': 1, 'failed': 0, 'fatal_errors': 0, 'exit_code': 0}, sort_keys=True).encode())
            log_ref = runtime.artifact(ident, b'probe log: passed\\n', 'text/plain')
            return {'outputs': {'test_results_ref': result_ref, 'log_ref': log_ref, 'exit_code': 0, 'ok': True}, 'usage': {'input_tokens': 2, 'output_tokens': 0, 'other_billable_tokens': 0, 'cost_microusd': 3, 'meter_id': 'probe-meter', 'price_version': 'fixed-probe-price'}}
        actor = {'kind': 'external_system', 'principal_id': 'local-probe', 'role': 'tester'}
        runtime = graph.Runtime(pathlib.Path(os.environ['WORKSPACE']), authority=Authority())
        runtime.adapters['check'] = {'actor': actor, 'tier': 1, 'invoke': invoke, 'max_tokens': 10, 'max_cost_microusd': 10, 'meter_id': 'probe-meter', 'price_version': 'fixed-probe-price', 'bounded': True, 'cancellable': True, 'idempotent': True, 'allowed': lambda inputs: True}
        inputs = {
            'code_ref': runtime.artifact(os.environ['WORKFLOW'], b'code for TEST-01\\n', 'text/plain'),
            'test_spec_ref': runtime.artifact(os.environ['WORKFLOW'], b'spec for TEST-01\\n', 'text/plain'),
            'request': 'TEST-01',
        }
        if os.environ['MODE'] == 'before_receipt_db_commit':
            with runtime.connection() as db:
                state = runtime.load(db, os.environ['WORKFLOW'])
                prepared = runtime.before_tool_call(db, state, 'TEST-01', inputs)
                runtime.save(db, state, {'before_tool_call': 'TEST-01'})
            attempt, adapter = prepared
            result = graph.bounded_call(adapter['invoke'], inputs, {'workspace': os.environ['WORKSPACE'], 'task': str(runtime.task_path(os.environ['WORKFLOW'])), 'intent': attempt['intent']}, attempt['timeout_s'])
            os._exit(81)
        runtime.execute(os.environ['WORKFLOW'], 'TEST-01', inputs)
        os._exit(82)
    """)
    env = dict(ENV, SCRIPTS=str(SCRIPTS), WORKSPACE=str(workspace_path),
               WORKFLOW=workflow_id, MODE=mode, LOG=str(log_path))
    return subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=30)


def probe_fault_windows(root):
    rows = []
    for mode, expected_rc in [('before_receipt_db_commit', 81), ('after_receipt_db_commit', 82)]:
        repo = workspace(root, f'fault-{mode}')
        log = root / f'fault-{mode}.jsonl'
        workflow_id = create_ready(repo)
        proc = crash_child(repo, workflow_id, mode, log)
        runtime = runtime_with_adapter(repo, log_path=log)
        after_crash = runtime.show(workflow_id)
        after_resume = runtime.resume(workflow_id)
        after_execute = runtime.execute(workflow_id, 'TEST-01', input_refs(runtime, workflow_id, 'TEST-01'))
        invokes = lines(log)
        rows.append({'mode': mode, 'process_rc': proc.returncode, 'expected_rc': expected_rc,
                     'after_crash': {'status': after_crash['status'], 'reason': after_crash['reason'],
                                     'receipts': len(after_crash['receipts']),
                                     'reservations': len(after_crash['reservations']),
                                     'attempt_statuses': [a['status'] for a in after_crash['attempts']]},
                     'after_resume': {'status': after_resume['status'], 'reason': after_resume['reason'],
                                      'receipts': len(after_resume['receipts']),
                                      'reservations': len(after_resume['reservations'])},
                     'after_execute': {'status': after_execute['status'], 'reason': after_execute['reason'],
                                       'receipts': len(after_execute['receipts']),
                                       'reservations': len(after_execute['reservations'])},
                     'invocation_count': len(invokes)})
    before = next(row for row in rows if row['mode'] == 'before_receipt_db_commit')
    after = next(row for row in rows if row['mode'] == 'after_receipt_db_commit')
    passed = (
        all(row['process_rc'] == row['expected_rc'] for row in rows)
        and before['after_crash']['receipts'] == 0
        and before['after_crash']['reservations'] == 1
        and before['after_resume']['reservations'] == 1
        and before['after_execute']['receipts'] == 0
        and before['invocation_count'] == 1
        and after['after_crash']['receipts'] == 1
        and after['after_resume']['receipts'] == 1
        and after['after_execute']['receipts'] == 1
        and after['invocation_count'] == 1
    )
    return classify('fault injection preserves reservations and avoids duplicate invokes on resume',
                    passed, trials=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    command = [sys.executable, str(Path(__file__).resolve()), '--output', str(args.output)]
    criteria = {'double_executes': 0, 'overspend': 0, 'state_corruption': 0, 'show_p95_ms_lt': 2000}
    with tempfile.TemporaryDirectory(prefix='graph-runtime-probe-') as temp:
        root = Path(temp).resolve()
        cases = [
            probe_show_load(root),
            probe_same_node(root),
            probe_distinct_caps(root),
            probe_breaker_half_open(root),
            probe_fault_windows(root),
        ]
    result = {
        'environment': {'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
                        'cwd': str(ROOT), 'runtime': str(RUNTIME_SCRIPT),
                        'runtime_sha256': hashlib.sha256(RUNTIME_SCRIPT.read_bytes()).hexdigest()},
        'raw_commands': [command],
        'method': 'Isolated temp Git workspaces; graph_runtime imported in real Python subprocesses; adapter invokes counted by append-only JSONL probe logs.',
        'criteria': criteria,
        'duration_seconds': time.perf_counter() - started,
        'cases': cases,
        'summary': {'passed': sum(case['pass'] for case in cases), 'total': len(cases),
                    'all_passed': all(case['pass'] for case in cases)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], ensure_ascii=False))
    print(f'Results: {args.output}')
    return 0 if result['summary']['all_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
