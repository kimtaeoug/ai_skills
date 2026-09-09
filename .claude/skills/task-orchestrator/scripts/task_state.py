#!/usr/bin/env python3
"""Local graph state and completion gates. Uses Python stdlib on macOS/Linux.

The calling Claude/Codex agent runs teams and records real user decisions; this
tool does not call models, run tests, or authenticate the speaker of a message.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


TASKS = Path('nimbalyst-local/tasks')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def identifier(value, prefix):
    need(isinstance(value, str) and re.fullmatch(rf'(?:{prefix})-[0-9]+', value), 'invalid local ID')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(workspace, *args):
    return subprocess.check_output(['git', '-C', str(workspace), *args], stderr=subprocess.PIPE)


def workspace_root(path):
    workspace = Path(path).resolve(strict=True)
    need(workspace.is_dir(), 'workspace must be a directory')
    root = Path(os.fsdecode(git(workspace, 'rev-parse', '--show-toplevel')).strip()).resolve()
    need(root == workspace, 'workspace must be the Git worktree root')
    return workspace


def snapshot(workspace):
    """Hash tracked and nonignored untracked files, including dirty content/modes.

    Task artifacts are excluded. Ignored inputs must be recorded as evidence by
    the caller; Git submodules require their own workspace run.
    """
    # ponytail: whole-worktree hash; add scoped manifests if large repos make this costly.
    workspace = workspace_root(workspace)
    names = sorted(set(git(workspace, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')))
    hasher = hashlib.sha256()
    for raw in names:
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative == TASKS or TASKS in relative.parents:
            continue
        path = workspace / relative
        hasher.update(raw + b'\0')
        if path.is_symlink():
            payload = b'link:' + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = str(path.stat().st_mode).encode() + b':' + path.read_bytes()
        elif not path.exists():
            payload = b'deleted'
        else:
            raise ValueError(f'unsupported directory/submodule input: {relative}')
        hasher.update(hashlib.sha256(payload).digest())
    return hasher.hexdigest()


@contextmanager
def locked(root):
    with (root / '.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def atomic_write(path, content):
    fd, temp = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save(task, state):
    # One atomic document includes history: no state/event-log dual-write window.
    # ponytail: task-sized JSON history; use SQLite if long histories become costly.
    atomic_write(task / 'state.json', json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def initialize(workspace, title):
    need(text(title), 'title is required')
    workspace = workspace_root(workspace)
    root = workspace / TASKS
    need(root.resolve() == root, 'task storage must not traverse symlinks')
    root.mkdir(parents=True, exist_ok=True)
    with locked(root):
        number = 1
        while (root / f'TASK-{number:04d}').exists():
            number += 1
        task = root / f'TASK-{number:04d}'
        task.mkdir()
        (task / 'artifacts').mkdir()
        save(task, {'schema': 1, 'id': task.name, 'workspace': str(workspace), 'title': title,
                    'revision': 0, 'phase': 'strategy', 'criteria_version': 0, 'plan_version': 0,
                    'criteria': [], 'items': {}, 'checks': {}, 'issues': {}, 'research': {},
                    'approvals': {}, 'attempts': 0, 'no_progress': 0, 'last_evaluation': None,
                    'ui_required': None, 'history': []})
    return task


def load(task):
    task = Path(task).absolute()
    need(task.resolve() == task, 'task path must not traverse symlinks')
    identifier(task.name, 'TASK')
    state = json.loads((task / 'state.json').read_text())
    need(state['schema'] == 1, 'unsupported state schema')
    workspace = workspace_root(state['workspace'])
    need(task == workspace / TASKS / state['id'], 'task is outside its workspace storage')
    return task, state


def evidence(task, path):
    need(text(path), 'evidence file is required')
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = task / candidate
    candidate = candidate.resolve(strict=True)
    need(candidate.is_relative_to(task / 'artifacts') and candidate.is_file(),
         'evidence must be a file inside this task artifacts directory')
    content = candidate.read_bytes()
    need(bool(content.strip()), 'evidence must not be empty')
    return {'path': str(candidate.relative_to(task)), 'sha256': digest(content)}


def phase(state, *allowed):
    need(state['phase'] in allowed, f"event not allowed in phase {state['phase']}")


def idle(state):
    need(not any(i['status'] == 'running' for i in state['items'].values()), 'settle running attempts first')


def versions(state):
    return [state['criteria_version'], state['plan_version']]


def approved_plan(state):
    need(state['approvals'].get('plan', {}).get('versions') == versions(state), 'plan approval is missing or stale')


def budget(value):
    need(isinstance(value, dict), 'budget is required')
    for key in ('max_attempts', 'max_no_progress'):
        need(type(value.get(key)) is int and value[key] > 0, f'{key} must be a positive integer')
    return {key: value[key] for key in ('max_attempts', 'max_no_progress')}


def conflict(left, right):
    for a in left['owns_files']:
        for b in right['owns_files']:
            x, y = PurePosixPath(a), PurePosixPath(b)
            if x == y or x in y.parents or y in x.parents:
                return True
    return bool(set(left['resources']) & set(right['resources']))


def plan_items(state, rows):
    need(isinstance(rows, list) and rows, 'plan needs at least one work item')
    items = {}
    for row in rows:
        ident = identifier(row['id'], 'DEV|FIX')
        need(ident not in items and text(row.get('description')), 'duplicate ID or missing description')
        for key in ('depends_on', 'owns_files', 'resources', 'criteria_ids'):
            need(isinstance(row.get(key), list) and all(text(x) for x in row[key]), f'invalid {key}')
        need(row['owns_files'] and row['criteria_ids'], 'ownership and acceptance criteria are required')
        for name in row['owns_files']:
            need(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts,
                 'ownership must use workspace-relative paths')
            need(not any(c in name for c in '*?[]'), 'ownership must use literal files or directories')
            owned = Path(state['workspace']) / name
            need(owned.resolve() == owned.absolute(), 'ownership must not traverse symlinks')
        need(set(row['criteria_ids']) <= {x['id'] for x in state['criteria']}, 'unknown acceptance criterion')
        need(row.get('risk') in ('low', 'high') and row.get('complexity') in ('small', 'large'), 'invalid work classification')
        attempts = sum(entry['event']['type'] == 'start' and entry['event'].get('id') == ident
                       for entry in state['history'])
        items[ident] = {**row, 'status': 'pending', 'attempt': attempts}
    pending, done = set(items), set()
    while pending:
        ready = {key for key in pending if set(items[key]['depends_on']) <= done}
        need(ready, 'dependency cycle or unknown dependency')
        pending -= ready
        done |= ready
    return items


def research_problems(task, state):
    problems = []
    for ident, result in state['research'].items():
        if not result['required']:
            continue
        if result['status'] != 'answered' or result['criteria_version'] != state['criteria_version']:
            problems.append(f'{ident}: required research unresolved or stale')
            continue
        try:
            valid = evidence(task, result['evidence']['path']) == result['evidence']
        except (ValueError, OSError):
            valid = False
        if not valid:
            problems.append(f'{ident}: research evidence changed')
    return problems


def check_problems(task, state):
    fingerprint = snapshot(state['workspace'])
    required = {check for criterion in state['criteria'] for check in criterion['checks']}
    problems = []
    if not state['criteria'] or not state['items'] or any(i['status'] != 'done' for i in state['items'].values()):
        problems.append('unfinished work')
    current = []
    for ident in sorted(required):
        result = state['checks'].get(ident)
        if not result:
            problems.append(f'{ident}: missing')
            continue
        if result['fingerprint'] != fingerprint or result['versions'] != versions(state):
            problems.append(f'{ident}: stale code or criteria')
            continue
        try:
            valid_evidence = evidence(task, result['evidence']['path']) == result['evidence']
        except (ValueError, OSError):
            valid_evidence = False
        if not valid_evidence:
            problems.append(f'{ident}: changed evidence')
        elif result['status'] != 'pass':
            problems.append(f"{ident}: {result['status']}")
        else:
            current.append(result)
    if not any(c['kind'] == 'code' for c in current):
        problems.append('code verification required')
    if state['ui_required'] is not False and not any(c['kind'] == 'ui' for c in current):
        problems.append('UI verification required')
    if any(i['status'] == 'open' for i in state['issues'].values()):
        problems.append('open issues')
    problems.extend(research_problems(task, state))
    return problems


def reduce_event(task, state, event):
    kind = event['type']
    need(state['phase'] not in ('completed', 'cancelled'), 'task is terminal')
    if kind == 'criteria':
        idle(state)
        rows = event['items']
        need(isinstance(rows, list) and rows, 'success conditions are required')
        ids = set()
        for row in rows:
            ident = identifier(row['id'], 'AC')
            need(ident not in ids and text(row.get('text')), 'duplicate criterion or missing text')
            need(isinstance(row.get('checks'), list) and row['checks'], 'each criterion needs checks')
            for check in row['checks']:
                identifier(check, 'TEST')
            ids.add(ident)
        need(event.get('ui_required') is None or type(event['ui_required']) is bool, 'invalid UI impact')
        need(text(event.get('ui_reason')), 'UI impact rationale is required')
        state.update(criteria=rows, criteria_version=state['criteria_version'] + 1,
                     ui_required=event.get('ui_required'), ui_reason=event['ui_reason'],
                     budget=budget(event['budget']), approvals={}, checks={}, phase='criteria_hil')
    elif kind == 'approve':
        gate = event['gate']
        need(gate in ('criteria', 'plan', 'reassess', 'final'), 'unknown approval gate')
        phase(state, gate + '_hil')
        idle(state)
        user = event['user']
        need(text(user.get('reference')) and text(user.get('message')), 'actual user message and reference required')
        approval = {'user': user, 'versions': versions(state)}
        if gate == 'final':
            approved_plan(state)
            need(not check_problems(task, state), 'verification is incomplete or stale')
            approval['fingerprint'] = snapshot(state['workspace'])
            state['phase'] = 'reporting'
        elif gate == 'reassess':
            route = event.get('route', 'planning')
            need(route in ('planning', 'triage', 'testing'), 'invalid reassessment route')
            if 'budget' in event:
                state['budget'] = budget(event['budget'])
            state['no_progress'] = 0
            state['phase'] = route
        else:
            state['phase'] = 'planning' if gate == 'criteria' else 'developing'
        state['approvals'][gate] = approval
    elif kind == 'research':
        phase(state, 'strategy', 'criteria_hil', 'planning')
        ident = identifier(event['id'], 'RES')
        need(text(event.get('question')), 'research question required')
        need(event.get('status') in ('answered', 'no-claims-found', 'no-confirmed-claims', 'synthesis-failed'),
             'explicit research status required')
        need(type(event.get('required')) is bool, 'research required flag must be boolean')
        previous = state['research'].get(ident, {})
        state['research'][ident] = {'question': event['question'], 'attempt': previous.get('attempt', 0) + 1,
                                    'status': event['status'], 'required': event['required'],
                                    'criteria_version': state['criteria_version'],
                                    'evidence': evidence(task, event['evidence'])}
    elif kind == 'plan':
        phase(state, 'planning', 'plan_hil')
        need(state['approvals'].get('criteria', {}).get('versions', [None])[0] == state['criteria_version'],
             'success conditions require user agreement')
        idle(state)
        need(not research_problems(task, state), 'required research is unresolved or stale')
        items = plan_items(state, event['items'])
        need(all(i.get('fixing_task_id', i['task_id']) in items for i in state['issues'].values() if i['status'] == 'open'),
             'plan would orphan an open issue; explicitly reassign it first')
        state['items'] = items
        state['plan_version'] += 1
        state['checks'] = {}
        state['approvals'].pop('final', None)
        state['phase'] = 'plan_hil'
    elif kind == 'start':
        phase(state, 'developing')
        approved_plan(state)
        need(state['attempts'] < state['budget']['max_attempts'], 'attempt budget reached; pause for HIL')
        item = state['items'][event['id']]
        need(item['status'] == 'pending', 'work item is not pending')
        need(all(state['items'][d]['status'] == 'done' for d in item['depends_on']), 'dependencies are unfinished')
        running = [i for i in state['items'].values() if i['status'] == 'running']
        for sibling in task.parent.glob('TASK-*'):
            if sibling != task and (sibling / 'state.json').exists():
                _, other = load(sibling)
                running += [i for i in other['items'].values() if i['status'] == 'running']
        need(len(running) < 4 and not any(conflict(item, i) for i in running), 'concurrency or ownership conflict')
        model = event['model']
        need(model.get('tier') in ('cheap', 'standard', 'high') and text(model.get('actual')), 'actual model and tier required')
        expected_tier = 'cheap' if item['risk'] == 'low' and item['complexity'] == 'small' else 'standard'
        need(text(model.get('reason')), 'model selection or escalation reason required')
        need(not (item['risk'] == 'high' and model['tier'] == 'cheap'), 'high-risk work requires a capable model')
        item.update(status='running', attempt=item['attempt'] + 1, model={**model, 'preferred_tier': expected_tier})
        state['attempts'] += 1
        state['checks'] = {}
        state['approvals'].pop('final', None)
        (task / 'artifacts' / item['id'] / f"attempt-{item['attempt']}").mkdir(parents=True, exist_ok=True)
    elif kind == 'finish':
        phase(state, 'developing')
        item = state['items'][event['id']]
        need(item['status'] == 'running' and event['attempt'] == item['attempt'], 'stale or inactive attempt')
        need(event['status'] in ('done', 'failed'), 'invalid implementation result')
        item.update(status=event['status'], evidence=evidence(task, event['evidence']), usage=event.get('usage'))
        if not any(i['status'] == 'running' for i in state['items'].values()):
            if any(i['status'] == 'failed' for i in state['items'].values()):
                state['phase'] = 'triage'
            elif all(i['status'] == 'done' for i in state['items'].values()):
                state['phase'] = 'testing'
    elif kind == 'check':
        phase(state, 'testing', 'triage')
        idle(state)
        need(all(i['status'] == 'done' for i in state['items'].values()), 'finish implementation before final tests')
        ident = identifier(event['id'], 'TEST')
        need(ident in {c for a in state['criteria'] for c in a['checks']}, 'check must map to agreed criteria')
        need(event['kind'] in ('code', 'ui'), 'invalid check kind')
        need(event['status'] in ('pass', 'fail', 'blocked', 'not-found', 'not-applicable'), 'invalid test status')
        need(text(event.get('command')), 'reproducible test command or browser procedure required')
        fingerprint = snapshot(state['workspace'])
        need(event['fingerprint'] == fingerprint, 'code changed during verification; rerun checks')
        if event['kind'] == 'ui':
            need(any(c['kind'] == 'code' and c['fingerprint'] == fingerprint and c['versions'] == versions(state)
                     for c in state['checks'].values()), 'record code verification before UI verification')
        state['checks'][ident] = {key: event[key] for key in ('kind', 'status', 'command', 'fingerprint')}
        state['checks'][ident].update(evidence=evidence(task, event['evidence']), versions=versions(state))
        state['approvals'].pop('final', None)
    elif kind == 'issue':
        need(set(event) <= {'type', 'id', 'task_id', 'description', 'status', 'evidence', 'check_id'},
             'unsupported issue fields; use issue-reassign to change repair owner')
        ident = identifier(event['id'], 'ISSUE')
        previous = state['issues'].get(ident)
        if previous:
            need(event['task_id'] == previous['task_id'] and event['description'] == previous['description'],
                 'issue origin and description are immutable; use issue-reassign')
        else:
            need(event['task_id'] in state['items'] and text(event.get('description')), 'issue needs work item and description')
        need(event['status'] in ('open', 'resolved'), 'invalid issue status')
        if event['status'] == 'resolved':
            need(previous, 'cannot resolve an unknown issue')
            owner = previous.get('fixing_task_id', previous['task_id'])
            need(owner in state['items'], 'issue needs a current repair owner')
            check = state['checks'].get(event.get('check_id'))
            need(check and check['status'] == 'pass' and check['fingerprint'] == snapshot(state['workspace'])
                 and check['versions'] == versions(state), 'issue resolution requires a current passing check')
            need(evidence(task, check['evidence']['path']) == check['evidence'], 'resolution evidence changed')
        state['issues'][ident] = {**(previous or {}), **event, 'evidence': evidence(task, event['evidence'])}
        state['approvals'].pop('final', None)
    elif kind == 'issue-reassign':
        phase(state, 'planning', 'plan_hil')
        idle(state)
        issue = state['issues'][event['id']]
        need(issue['status'] == 'open' and text(event.get('reason')), 'open issue and reassignment reason required')
        issue['fixing_task_id'] = identifier(event['fixing_task_id'], 'DEV|FIX')
        state['approvals'].pop('plan', None)
    elif kind == 'rework':
        phase(state, 'triage', 'final_hil', 'testing')
        idle(state)
        approved_plan(state)
        need(text(event.get('reason')) and isinstance(event.get('ids'), list) and event['ids'], 'rework IDs and reason required')
        affected = set(event['ids'])
        need(affected <= state['items'].keys(), 'unknown rework item')
        while True:
            more = {key for key, item in state['items'].items() if set(item['depends_on']) & affected}
            if more <= affected:
                break
            affected |= more
        for ident in affected:
            state['items'][ident]['status'] = 'pending'
        state['checks'] = {}
        state['approvals'].pop('final', None)
        state['phase'] = 'developing'
    elif kind == 'evaluate':
        phase(state, 'testing', 'triage', 'final_hil', 'reporting')
        idle(state)
        problems = check_problems(task, state)
        signature = sorted(problems)
        last = state['last_evaluation']
        if last and last['attempts'] != state['attempts']:
            state['no_progress'] = state['no_progress'] + 1 if last['problems'] == signature else 0
        state['last_evaluation'] = {'attempts': state['attempts'], 'problems': signature}
        final = state['approvals'].get('final', {})
        if not problems and final.get('versions') == versions(state) and final.get('fingerprint') == snapshot(state['workspace']):
            state['phase'] = 'reporting'
            return
        state['approvals'].pop('final', None)
        if not problems:
            state['phase'] = 'final_hil'
        elif state['attempts'] >= state['budget']['max_attempts'] or state['no_progress'] >= state['budget']['max_no_progress']:
            state['phase'] = 'reassess_hil'
        elif any(c['status'] == 'fail' for c in state['checks'].values()) or any(i['status'] == 'open' for i in state['issues'].values()) or any(i['status'] == 'failed' for i in state['items'].values()):
            state['phase'] = 'triage'
        else:
            state['phase'] = 'reassess_hil'
    elif kind == 'pause':
        idle(state)
        need(text(event.get('reason')), 'pause reason required')
        state['phase'] = 'reassess_hil'
        state['approvals'].pop('final', None)
    elif kind == 'complete':
        phase(state, 'reporting')
        approved_plan(state)
        final = state['approvals'].get('final', {})
        need(final.get('versions') == versions(state) and final.get('fingerprint') == snapshot(state['workspace']),
             'final approval is missing or stale; code changed')
        need(not check_problems(task, state), 'verification is incomplete or stale')
        need(text(event.get('summary')), 'final summary required')
        state['summary'] = event['summary']
        state['limitations'] = event.get('limitations', [])
        need(isinstance(state['limitations'], list) and all(text(x) for x in state['limitations']), 'invalid limitations')
        state['phase'] = 'completed'
    elif kind == 'cancel':
        idle(state)
        need(text(event.get('reason')), 'cancellation reason required')
        state['phase'] = 'cancelled'
    else:
        raise ValueError(f'unknown event type: {kind}')


def report(state):
    lines = [f"# {state['id']}: {state['title']}", '', f"Status: {state['phase']}; state revision: {state['revision']}", '', state.get('summary', ''),
             '', '## Acceptance criteria', '']
    for item in state['criteria']:
        lines.append(f"- {item['id']}: {item['text']} — {', '.join(item['checks'])}")
    lines += ['', '## Work and models', '']
    for item in state['items'].values():
        lines.append(f"- {item['id']}: {item['status']}; attempt {item['attempt']}; model {item.get('model', {}).get('actual', 'unknown')}; files {', '.join(item['owns_files'])}; usage {json.dumps(item.get('usage'), ensure_ascii=False)}")
    lines += ['', '## Verification', '']
    for ident, check in state['checks'].items():
        lines.append(f"- {ident} ({check['kind']}): {check['status']}; `{check['command']}`; [{check['evidence']['path']}]({check['evidence']['path']}); code `{check['fingerprint']}`")
    lines += ['', '## Research', '']
    for ident, research in state['research'].items():
        lines.append(f"- {ident}: {research['status']}; [{research['question']}]({research['evidence']['path']})")
    lines += ['', '## Attempt history', '']
    for entry in state['history']:
        event = entry['event']
        if event['type'] in ('start', 'finish', 'rework'):
            lines.append(f"- revision {entry['revision']}: {json.dumps(event, ensure_ascii=False)}")
    lines += ['', '## Issues', '', json.dumps(state['issues'], ensure_ascii=False, indent=2),
              '', '## Human decisions', '', json.dumps(state['approvals'], ensure_ascii=False, indent=2),
              '', '## Limitations', '', *[f'- {x}' for x in state.get('limitations', [])],
              '', 'Full attempts, research, decisions and transitions: [state.json](state.json).', '']
    return '\n'.join(lines)


def apply(task, expected_revision, event):
    task, _ = load(task)
    # Serialize state mutations within one worktree, including cross-task claims.
    with locked(task.parent):
        task, state = load(task)
        need(type(expected_revision) is int and expected_revision == state['revision'], 'state revision conflict; reload before retry')
        need(isinstance(event, dict) and text(event.get('type')), 'event object with type required')
        before = state['phase']
        try:
            reduce_event(task, state, event)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f'malformed event: {exc}') from exc
        state['revision'] += 1
        state['history'].append({'revision': state['revision'], 'at': datetime.now(timezone.utc).isoformat(),
                                 'from': before, 'to': state['phase'], 'event': event})
        if event['type'] in ('complete', 'cancel', 'pause'):
            # Report first: a failed write cannot leave state claiming completion.
            atomic_write(task / 'report.md', report(state))
        save(task, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='allocate a task ID within a Git workspace')
    init.add_argument('--workspace', required=True)
    init.add_argument('--title', required=True)
    for command in ('show', 'snapshot', 'apply'):
        p = sub.add_parser(command)
        p.add_argument('--task', required=True)
        if command == 'apply':
            p.add_argument('--expected', type=int, required=True, help='revision returned by show')
            p.add_argument('--event', required=True, help='JSON event file, or - for stdin')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            output = {'task': str(initialize(args.workspace, args.title))}
        else:
            task, state = load(args.task)
            if args.command == 'show':
                output = state
            elif args.command == 'snapshot':
                output = {'fingerprint': snapshot(state['workspace'])}
            else:
                raw = sys.stdin.read() if args.event == '-' else Path(args.event).read_text()
                output = apply(task, args.expected, json.loads(raw))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'task-state: {exc}\n')


if __name__ == '__main__':
    main()
