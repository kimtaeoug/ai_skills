"""Bounded reliability probe for task-orchestrator.

Run: python3 tests/probe-task-orchestrator-reliability.py --output /tmp/reliability.json

Uses isolated temporary Git workspaces and real CLI subprocesses for concurrent
mutations. Fault injection is deterministic process-exit around os.replace; it is
not a power-loss or filesystem durability claim.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import textwrap
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.claude/skills/task-orchestrator/scripts/task_state.py'
SPEC = importlib.util.spec_from_file_location('task_state', SCRIPT)
ENGINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENGINE)

ENV = {key: os.environ[key] for key in ('PATH', 'TMPDIR', 'SYSTEMROOT') if key in os.environ}
ENV.update(PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
USER = {'reference': 'probe:synthetic-hil', 'message': 'TEST ONLY synthetic approval'}


def run(args, event=None, timeout=30):
    start = time.perf_counter()
    proc = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          input=json.dumps(event) if event is not None else None,
                          capture_output=True, text=True, env=ENV, timeout=timeout)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {'ok': proc.returncode == 0, 'rc': proc.returncode, 'ms': elapsed_ms,
            'stdout': proc.stdout.strip(), 'stderr': proc.stderr.strip()}


def workspace(root, name):
    path = root / name
    path.mkdir()
    subprocess.run(['git', 'init', '-q', str(path)], check=True, env=ENV)
    (path / 'app.txt').write_text('fixture\n')
    return path


def state(task):
    return json.loads((task / 'state.json').read_text())


def evidence(task, name='result.txt', text='synthetic evidence'):
    path = task / 'artifacts' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


def apply(task, event):
    return ENGINE.apply(task, state(task)['revision'], event)


def prepare(task, owner='app.txt', budget=20):
    apply(task, {'type': 'criteria',
                 'items': [{'id': 'AC-01', 'text': 'Synthetic acceptance', 'checks': ['TEST-01']}],
                 'ui_required': False, 'ui_reason': 'CLI-only probe',
                 'budget': {'max_attempts': budget, 'max_no_progress': 2}})
    apply(task, {'type': 'approve', 'gate': 'criteria', 'user': USER})
    apply(task, {'type': 'plan', 'items': [{'id': 'DEV-01', 'description': 'Synthetic work',
                                           'depends_on': [], 'owns_files': [owner], 'resources': [],
                                           'criteria_ids': ['AC-01'], 'risk': 'low', 'complexity': 'small'}]})
    apply(task, {'type': 'approve', 'gate': 'plan', 'user': USER})


def start_event():
    return {'type': 'start', 'id': 'DEV-01',
            'model': {'tier': 'cheap', 'actual': 'fixture-no-model', 'reason': 'Reliability probe'}}


def classify(name, passed, **details):
    return {'name': name, 'pass': bool(passed), **details}


def parallel_cli(calls, workers):
    def one(call):
        return run(call['args'], call.get('event'))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, calls))


def probe_parallel_init(root, count=64):
    repo = workspace(root, 'parallel-init')
    calls = [{'args': ['init', '--workspace', repo, '--title', f'task-{i}']} for i in range(count)]
    rows = parallel_cli(calls, workers=16)
    tasks = []
    for row in rows:
        if row['ok']:
            tasks.append(json.loads(row['stdout'])['task'])
    unique = len(set(tasks)) == count
    valid_states = all((Path(task) / 'state.json').is_file() for task in tasks)
    ids = sorted(Path(task).name for task in tasks)
    return classify('parallel task ID allocation', len(tasks) == count and unique and valid_states,
                    attempts=count, successes=len(tasks), unique_ids=len(set(tasks)),
                    min_id=ids[0] if ids else None, max_id=ids[-1] if ids else None,
                    failures=[row['stderr'] for row in rows if not row['ok']])


def probe_revision_race(root, rounds=10, contenders=32):
    details = []
    for round_index in range(rounds):
        repo = workspace(root, f'revision-race-{round_index}')
        task = ENGINE.initialize(repo, 'same revision race')
        event = {'type': 'pause', 'reason': 'one writer should win'}
        rows = parallel_cli([{'args': ['apply', '--task', task, '--expected', 0, '--event', '-'],
                              'event': event} for _ in range(contenders)], workers=contenders)
        final = state(task)
        successes = sum(row['ok'] for row in rows)
        conflicts = sum('revision conflict' in row['stderr'] for row in rows if not row['ok'])
        details.append({'successes': successes, 'revision_conflicts': conflicts,
                        'final_revision': final['revision'], 'history_entries': len(final['history'])})
    passed = all(row == {'successes': 1, 'revision_conflicts': contenders - 1,
                         'final_revision': 1, 'history_entries': 1} for row in details)
    return classify('same-revision write conflict', passed, rounds=rounds,
                    contenders_per_round=contenders, details=details)


def probe_cross_task_conflict(root, rounds=10):
    details = []
    for round_index in range(rounds):
        repo = workspace(root, f'cross-task-conflict-{round_index}')
        tasks = [ENGINE.initialize(repo, f'claim-{i}') for i in range(2)]
        for task in tasks:
            prepare(task, owner='app.txt')
        rows = parallel_cli([{'args': ['apply', '--task', task, '--expected', state(task)['revision'], '--event', '-'],
                              'event': start_event()} for task in tasks], workers=2)
        states = [state(task) for task in tasks]
        details.append({'successes': sum(row['ok'] for row in rows),
                        'conflicts': sum('conflict' in row['stderr'] for row in rows if not row['ok']),
                        'running_items': sum(s['items']['DEV-01']['status'] == 'running' for s in states)})
    passed = all(row == {'successes': 1, 'conflicts': 1, 'running_items': 1} for row in details)
    return classify('cross-task same-file claim', passed, rounds=rounds, contenders_per_round=2,
                    details=details)


def probe_workspace_cap(root, rounds=10, contenders=8, expected_running=4):
    details = []
    for round_index in range(rounds):
        repo = workspace(root, f'workspace-cap-{round_index}')
        tasks = [ENGINE.initialize(repo, f'independent-{i}') for i in range(contenders)]
        for index, task in enumerate(tasks):
            prepare(task, owner=f'file-{index}.txt')
        rows = parallel_cli([{'args': ['apply', '--task', task, '--expected', state(task)['revision'], '--event', '-'],
                              'event': start_event()} for task in tasks], workers=contenders)
        details.append({'successes': sum(row['ok'] for row in rows),
                        'rejected_by_cap': sum('concurrency or ownership conflict' in row['stderr']
                                               for row in rows if not row['ok']),
                        'running_items': sum(state(task)['items']['DEV-01']['status'] == 'running'
                                             for task in tasks)})
    expected = {'successes': expected_running, 'rejected_by_cap': contenders - expected_running,
                'running_items': expected_running}
    return classify('workspace running cap', all(row == expected for row in details),
                    rounds=rounds, contenders_per_round=contenders,
                    configured_cap=expected_running, details=details)


def complete_ready_task(repo):
    task = ENGINE.initialize(repo, 'completion crash window')
    prepare(task)
    apply(task, start_event())
    apply(task, {'type': 'finish', 'id': 'DEV-01', 'attempt': 1, 'status': 'done',
                 'evidence': evidence(task, 'DEV-01.txt', 'done')})
    fingerprint = ENGINE.snapshot(repo)
    apply(task, {'type': 'check', 'id': 'TEST-01', 'kind': 'code', 'status': 'pass',
                 'command': 'synthetic check', 'fingerprint': fingerprint,
                 'evidence': evidence(task, 'TEST-01.txt', 'pass')})
    apply(task, {'type': 'evaluate'})
    apply(task, {'type': 'approve', 'gate': 'final', 'user': USER})
    return task


def crash_apply(task, mode):
    code = textwrap.dedent("""
        import importlib.util, json, os, pathlib
        script = pathlib.Path(os.environ['TASK_STATE_SCRIPT'])
        task = pathlib.Path(os.environ['TASK_PATH'])
        mode = os.environ['FAULT_MODE']
        spec = importlib.util.spec_from_file_location('task_state', script)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        real_replace = engine.os.replace
        calls = {'n': 0}
        def replace(src, dst):
            calls['n'] += 1
            if mode == 'before_report_replace' and calls['n'] == 1:
                os._exit(71)
            if mode == 'before_state_replace' and calls['n'] == 2:
                os._exit(71)
            real_replace(src, dst)
            if mode == 'after_report_replace' and calls['n'] == 1:
                os._exit(72)
            if mode == 'after_state_replace' and calls['n'] == 2:
                os._exit(73)
        engine.os.replace = replace
        state = json.loads((task / 'state.json').read_text())
        engine.apply(task, state['revision'], {'type': 'complete', 'summary': 'Synthetic complete'})
    """)
    env = dict(ENV, TASK_STATE_SCRIPT=str(SCRIPT), TASK_PATH=str(task), FAULT_MODE=mode)
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=30)


def probe_crash_windows(root):
    rows = []
    expected_rc = {'before_report_replace': 71, 'after_report_replace': 72,
                   'before_state_replace': 71, 'after_state_replace': 73}
    for mode in expected_rc:
        repo = workspace(root, f'crash-{mode}')
        task = complete_ready_task(repo)
        before = state(task)
        proc = crash_apply(task, mode)
        after = state(task)
        report_text = (task / 'report.md').read_text() if (task / 'report.md').is_file() else ''
        recovery = None
        if after['phase'] == 'reporting':
            recovery = run(['apply', '--task', task, '--expected', after['revision'], '--event', '-'],
                           {'type': 'complete', 'summary': 'Recovered complete'})
            after_recovery = state(task)
            recovery = {'ok': recovery['ok'], 'phase_after': after_recovery['phase'],
                        'revision_after': after_recovery['revision'],
                        'report_matches_state': f"state revision: {after_recovery['revision']}"
                                                in (task / 'report.md').read_text()}
        report_matches_state = bool(report_text) and f"state revision: {after['revision']}" in report_text
        rows.append({'mode': mode, 'process_rc': proc.returncode,
                     'state_phase': after['phase'], 'state_revision': after['revision'],
                     'state_unchanged': after == before,
                     'report_exists': bool(report_text),
                     'report_claims_completed': 'Status: completed' in report_text,
                     'report_matches_state': report_matches_state,
                     'recovery': recovery})
    expected_exits = all(row['process_rc'] == expected_rc[row['mode']] for row in rows)
    pre_state_modes = {'before_report_replace', 'after_report_replace', 'before_state_replace'}
    pre_state_unchanged = all(row['state_unchanged'] for row in rows if row['mode'] in pre_state_modes)
    false_authoritative_completion = any(row['state_phase'] == 'completed' and row['process_rc'] != 0
                                         and row['mode'] != 'after_state_replace'
                                         for row in rows)
    report_ahead_modes = {'after_report_replace', 'before_state_replace'}
    known_report_ahead_window = all(row['report_claims_completed'] and row['state_phase'] == 'reporting'
                                    and row['recovery']['phase_after'] == 'completed'
                                    and row['recovery']['report_matches_state']
                                    for row in rows if row['mode'] in report_ahead_modes)
    all_reporting_recoverable = all(row['recovery'] and row['recovery']['ok']
                                    and row['recovery']['phase_after'] == 'completed'
                                    and row['recovery']['report_matches_state']
                                    for row in rows if row['mode'] in pre_state_modes)
    completed_after_state_replace = any(row['mode'] == 'after_state_replace'
                                        and row['state_phase'] == 'completed'
                                        and row['report_claims_completed']
                                        and row['report_matches_state'] for row in rows)
    return classify('crash windows around report/state writes',
                    expected_exits and pre_state_unchanged and not false_authoritative_completion
                    and known_report_ahead_window and all_reporting_recoverable
                    and completed_after_state_replace,
                    trials=rows, false_authoritative_completion=false_authoritative_completion,
                    known_report_ahead_window=known_report_ahead_window,
                    expected_exits=expected_exits, pre_state_unchanged=pre_state_unchanged,
                    all_reporting_recoverable=all_reporting_recoverable,
                    completed_after_state_replace=completed_after_state_replace)


def probe_report_write_failure(root):
    repo = workspace(root, 'report-write-failure')
    task = complete_ready_task(repo)
    revision = state(task)['revision']
    (task / 'report.md').mkdir()
    row = run(['apply', '--task', task, '--expected', revision, '--event', '-'],
              {'type': 'complete', 'summary': 'Cannot save report'})
    final = state(task)
    return classify('report write failure does not complete state',
                    not row['ok'] and final['revision'] == revision and final['phase'] == 'reporting',
                    cli_rc=row['rc'], stderr=row['stderr'], revision_before=revision,
                    revision_after=final['revision'], phase_after=final['phase'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='orchestrator-reliability-') as temp:
        root = Path(temp).resolve()
        probes = [
            probe_parallel_init(root),
            probe_revision_race(root),
            probe_cross_task_conflict(root),
            probe_workspace_cap(root),
            probe_crash_windows(root),
            probe_report_write_failure(root),
        ]
    result = {
        'environment': {'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count()},
        'method': 'Isolated temp Git repos; real CLI subprocesses for concurrent mutations; deterministic os._exit fault injection.',
        'duration_seconds': time.perf_counter() - started,
        'thresholds': {'unexpected_errors': 0, 'duplicate_task_ids': 0, 'accepted_stale_revision_writers': 0,
                       'false_authoritative_completion_after_crash': 0},
        'probes': probes,
        'summary': {'passed': sum(row['pass'] for row in probes), 'total': len(probes)},
        'limitations': ['Does not prove power-loss durability or fsync directory semantics.',
                        'Does not call real models, browsers, or external services.',
                        'Synthetic HIL references are test-only and not user authentication.'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], ensure_ascii=False))
    print(f'Results: {args.output}')
    return 0 if all(row['pass'] for row in probes) else 1


if __name__ == '__main__':
    sys.exit(main())
