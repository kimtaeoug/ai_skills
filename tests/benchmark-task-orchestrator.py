"""Bounded stdlib/real-CLI load probe; no models, network, or production edits.

Run: python3 tests/benchmark-task-orchestrator.py --output /tmp/load.json
Temporary Git fixtures are removed by TemporaryDirectory. History scaling uses
explicitly synthetic history; throughput uses only real committed CLI events.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / '.claude/skills/task-orchestrator/scripts/task_state.py'
spec = importlib.util.spec_from_file_location('task_state', SCRIPT)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
# Do not forward tokens, credentials, or production settings to test subprocesses.
ENV = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SYSTEMROOT') if k in os.environ}
ENV.update(PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
CRITERIA = {'type': 'criteria', 'items': [{'id': 'AC-01', 'text': 'Synthetic benchmark', 'checks': ['TEST-01']}],
            'ui_required': False, 'ui_reason': 'CLI fixture only',
            'budget': {'max_attempts': 100, 'max_no_progress': 2}}


def cli(*args, event=None):
    start = time.perf_counter()
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                            input=json.dumps(event) if event is not None else None,
                            capture_output=True, text=True, env=ENV, timeout=30)
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode:
        return elapsed, None, result.stderr.strip()
    try:
        return elapsed, json.loads(result.stdout), None
    except ValueError:
        return elapsed, None, 'non-JSON successful CLI output'


def stats(samples, errors, wall=None):
    ordered = sorted(samples)
    result = {'samples': len(samples), 'errors': errors,
              'p50_ms': statistics.median(ordered),
              'p95_ms': ordered[math.ceil(len(ordered) * .95) - 1],
              'max_ms': max(ordered), 'raw_ms': samples}
    if wall is not None:
        result.update(wall_seconds=wall, successful_ops_per_second=(len(samples) - len(errors)) / wall)
    result['pass'] = not errors and result['p95_ms'] <= 2000
    return result


def workspace(root, name):
    path = root / name
    path.mkdir()
    subprocess.run(['git', 'init', '-q', str(path)], check=True, env=ENV)
    return path


def read_state(task):
    return json.loads((task / 'state.json').read_text())


def load_matrix(root):
    results = []
    for operation in ('show', 'apply'):
        for clients in (1, 4, 8, 16):
            repo = workspace(root, f'{operation}-{clients}')
            tasks = [engine.initialize(repo, f'client-{i}') for i in range(clients)]
            for task in tasks:
                cli('show', '--task', task)  # Untimed warmup, no cache flushing.

            def lane(task):
                samples, errors = [], []
                for revision in range(96 // clients):
                    if operation == 'show':
                        elapsed, result, error = cli('show', '--task', task)
                    else:
                        elapsed, result, error = cli('apply', '--task', task, '--expected', revision,
                                                     '--event', '-', event=CRITERIA)
                    samples.append(elapsed)
                    if error:
                        errors.append(error)
                    elif result['revision'] != (revision + 1 if operation == 'apply' else 0):
                        errors.append('unexpected returned revision')
                return samples, errors

            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=clients) as pool:
                lanes = list(pool.map(lane, tasks))
            wall = time.perf_counter() - start
            samples = [value for row, _ in lanes for value in row]
            errors = [value for _, row in lanes for value in row]
            expected = 96 // clients if operation == 'apply' else 0
            integrity = all((s := read_state(task))['revision'] == expected
                            and len(s['history']) == expected
                            and [e['revision'] for e in s['history']] == list(range(1, expected + 1))
                            for task in tasks)
            result = dict(operation=operation, clients=clients, integrity=integrity,
                          **stats(samples, errors, wall))
            result['pass'] &= integrity
            results.append(result)
            print(f'{operation} clients={clients}: p95={result["p95_ms"]:.1f}ms '
                  f'ops/s={result["successful_ops_per_second"]:.1f} errors={len(errors)} integrity={integrity}', flush=True)
    return results


def scaling(root):
    results = []
    for files in (100, 1000, 5000):
        repo = workspace(root, f'files-{files}')
        for i in range(files):
            (repo / f'source-{i}.txt').write_bytes(b'x' * 4096)
        task = engine.initialize(repo, 'Snapshot scale')
        cli('snapshot', '--task', task)
        samples, errors, fingerprints = [], [], set()
        for _ in range(30):
            elapsed, result, error = cli('snapshot', '--task', task)
            samples.append(elapsed)
            if error:
                errors.append(error)
            else:
                fingerprints.add(result['fingerprint'])
        result = dict(operation='snapshot', files=files, source_bytes=files * 4096,
                      deterministic=len(fingerprints) == 1, **stats(samples, errors))
        result['pass'] &= result['deterministic']
        results.append(result)
        print(f'snapshot files={files}: p95={result["p95_ms"]:.1f}ms', flush=True)
    for entries in (10, 1000, 10000):
        repo = workspace(root, f'history-{entries}')
        task = engine.initialize(repo, 'Synthetic history scale')
        state = read_state(task)
        state['revision'] = entries
        state['history'] = [{'revision': i + 1, 'at': 'synthetic', 'from': 'criteria_hil',
                             'to': 'criteria_hil', 'event': CRITERIA} for i in range(entries)]
        engine.save(task, state)
        size = (task / 'state.json').stat().st_size
        samples, errors = [], []
        for i in range(30):
            elapsed, _, error = cli('apply', '--task', task, '--expected', entries + i,
                                     '--event', '-', event=CRITERIA)
            samples.append(elapsed)
            if error:
                errors.append(error)
        result = dict(operation='apply-history', seeded_history_entries=entries,
                      initial_state_bytes=size, **stats(samples, errors))
        results.append(result)
        print(f'history entries={entries}: p95={result["p95_ms"]:.1f}ms', flush=True)
    # A start scans every sibling task, including inactive/completed tasks.
    for count in (1, 100, 300):
        repo = workspace(root, f'census-{count}')
        task = engine.initialize(repo, 'Start scan scale')
        for i in range(count - 1):
            engine.initialize(repo, f'inactive-{i}')
        def apply(event):
            return engine.apply(task, read_state(task)['revision'], event)
        apply(CRITERIA)
        user = {'reference': 'benchmark:synthetic', 'message': 'TEST ONLY approval'}
        apply({'type': 'approve', 'gate': 'criteria', 'user': user})
        apply({'type': 'plan', 'items': [{'id': 'DEV-01', 'description': 'Synthetic work',
              'depends_on': [], 'owns_files': ['app.txt'], 'resources': [], 'criteria_ids': ['AC-01'],
              'risk': 'low', 'complexity': 'small'}]})
        apply({'type': 'approve', 'gate': 'plan', 'user': user})
        evidence = task / 'artifacts/result.txt'
        evidence.write_text('TEST ONLY synthetic finish, no external model called')
        samples, errors = [], []
        for i in range(10):
            elapsed, _, error = cli('apply', '--task', task, '--expected', read_state(task)['revision'],
                                     '--event', '-', event={'type': 'start', 'id': 'DEV-01',
                                     'model': {'tier': 'cheap', 'actual': 'fixture-no-model', 'reason': 'Load probe'}})
            samples.append(elapsed)
            if error:
                errors.append(error)
                break
            apply({'type': 'finish', 'id': 'DEV-01', 'attempt': i + 1, 'status': 'done', 'evidence': str(evidence)})
            apply({'type': 'rework', 'ids': ['DEV-01'], 'reason': 'Synthetic next sample'})
        result = dict(operation='start-task-census', workspace_tasks=count, **stats(samples, errors))
        results.append(result)
        print(f'start workspace_tasks={count}: p95={result["p95_ms"]:.1f}ms', flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'environment': {'python': sys.version, 'platform': platform.platform(),
                             'cpu_count': os.cpu_count(), 'script_sha256': hashlib.sha256(SCRIPT.read_bytes()).hexdigest()},
              'method': 'Real CLI including Python startup, OS-cache warm, closed-loop clients; nearest-rank p95.',
              'thresholds': {'p95_ms': 2000, 'unexpected_errors': 0, 'integrity_failures': 0},
              'limitations': ['Local provisional thresholds, not production SLA.', 'No external models/browser.',
                              'History sizes use synthetic seeded entries.', 'No CPU/RSS or power-loss measurement.',
                              'Closed-loop results exclude queued arrivals outside each client; not a saturation SLA.']}
    with tempfile.TemporaryDirectory(prefix='orchestrator-load-') as temporary:
        root = Path(temporary).resolve()
        result['load'] = load_matrix(root)
        result['scaling'] = scaling(root)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'Results: {args.output}', flush=True)
    return 0 if all(row['pass'] for row in result['load'] + result['scaling']) else 1


if __name__ == '__main__':
    sys.exit(main())
