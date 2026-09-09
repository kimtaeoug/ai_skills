#!/usr/bin/env python3
"""Opt-in v2 execution authority. No native provider or human identity is assumed.

Trusted host code registers bounded adapters and an identity authority. JSON input
cannot register executable code, certify usage, or manufacture human identity.
The local OS account / trusted host is the security boundary, not a Python sandbox.
"""
import argparse
from contextlib import closing, contextmanager
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import select
import signal
import sqlite3
import sys
import time

from runtime_policy import DEFAULTS, merge_policy, new_clock, remaining, retry_delay, set_hil, tick
from runtime_contracts import ARTIFACT_REF as ARTIFACT_SCHEMA, STAGE_SCHEMAS
from task_state import TASKS, atomic_write, need, snapshot, workspace_root


RETRYABLE_ERRORS = {'timeout', 'service_unavailable', 'rate_limit', 'connection_error'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def schema_check(value, schema, path='$'):
    """Small closed JSON-schema vocabulary; unsupported keywords are rejected."""
    need(isinstance(schema, dict) and set(schema) <= {'type', 'properties', 'required', 'items', 'enum', 'minimum', 'minItems'}, 'unsupported schema')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool}
    kind = schema.get('type')
    need(kind in types, 'schema type required')
    if 'enum' in schema:
        need(isinstance(schema['enum'], list) and schema['enum'], 'enum must be a nonempty list')
        for item in schema['enum']:
            need(number(item) if kind == 'number' else type(item) is types[kind], 'enum value has wrong type')
    valid = number(value) if kind == 'number' else type(value) is types[kind]
    if not valid:
        return 'invalid', [path + ': wrong type']
    if 'enum' in schema and value not in schema['enum']:
        return 'invalid', [path + ': outside enum']
    if 'minimum' in schema and (not number(value) or value < schema['minimum']):
        return 'invalid', [path + ': below minimum']
    if kind == 'object':
        props = schema.get('properties', {})
        if set(value) - set(props):
            return 'invalid', [path + ': unknown fields']
        missing = set(schema.get('required', props)) - set(value)
        if missing:
            return 'missing', [path + '.' + name for name in sorted(missing)]
        for key, item in value.items():
            result = schema_check(item, props[key], path + '.' + key)
            if result[0] != 'pass':
                return result
    if kind == 'array':
        if len(value) < schema.get('minItems', 0):
            return 'missing', [path + ': empty array']
        for index, item in enumerate(value):
            result = schema_check(item, schema['items'], f'{path}[{index}]')
            if result[0] != 'pass':
                return result
    return 'pass', []


def validate_schema(schema):
    need(isinstance(schema, dict), 'schema object required')
    examples = {'object': {}, 'array': [], 'string': '', 'integer': 0, 'number': 0, 'boolean': False}
    need(schema.get('type') in examples, 'invalid schema type')
    schema_check(examples[schema['type']], schema)
    if schema['type'] == 'object':
        props = schema.get('properties', {})
        need(isinstance(props, dict), 'schema properties required')
        need(isinstance(schema.get('required', []), list) and set(schema.get('required', [])) <= set(props), 'unknown required field')
        for nested in props.values():
            validate_schema(nested)
    if schema['type'] == 'array':
        validate_schema(schema.get('items'))
    if 'minimum' in schema:
        need(schema['type'] in ('integer', 'number') and number(schema['minimum']), 'minimum must be finite numeric')
    if 'minItems' in schema:
        need(schema['type'] == 'array' and type(schema['minItems']) is int and schema['minItems'] >= 0, 'invalid minItems')


def validate_contract(contract, policy):
    need(isinstance(contract, dict) and set(contract) == {'title', 'approvers', 'nodes', 'edges'}, 'invalid contract fields')
    need(isinstance(contract['title'], str) and contract['title'].strip(), 'title required')
    need(isinstance(contract['approvers'], list) and contract['approvers'] and all(isinstance(x, str) and x for x in contract['approvers']), 'approvers required')
    need(isinstance(contract['nodes'], list) and contract['nodes'], 'nodes required')
    ids = set()
    for node in contract['nodes']:
        required = {'node_id', 'kind', 'actor', 'input_schema', 'output_schema', 'required_evidence', 'tool_routes'}
        need(required <= set(node) <= required | {'timeout_s', 'retry_policy', 'quality_policy'}, 'invalid node fields')
        ident = node['node_id']
        need(isinstance(ident, str) and re.fullmatch(r'[A-Z]+-[0-9]+', ident) and ident not in ids, 'duplicate/invalid node ID')
        ids.add(ident)
        need(node['kind'] in ('contract_hil', 'strategy', 'research', 'plan', 'plan_hil', 'develop', 'code_test', 'screen_test', 'visual_review', 'evidence_gate', 'human_approval_gate', 'final_hil', 'report'), 'unknown stage kind')
        actor = node['actor']
        need(set(actor) == {'kind', 'principal_id', 'role'} and actor['kind'] in ('agent', 'human', 'external_system') and all(isinstance(x, str) and x for x in actor.values()), 'invalid actor')
        validate_schema(node['input_schema'])
        validate_schema(node['output_schema'])
        for direction, field in (('input', 'input_schema'), ('output', 'output_schema')):
            base = STAGE_SCHEMAS[node['kind']][direction]
            actual = node[field]
            need(actual['type'] == 'object' and set(base['required']) <= set(actual.get('required', actual.get('properties', {}))), 'stage required fields cannot be omitted')
            need(all(actual.get('properties', {}).get(key) == value for key, value in base['properties'].items()), 'canonical stage property cannot be weakened')
        need(isinstance(node['tool_routes'], list) and node['tool_routes'] and all(isinstance(x, str) and x for x in node['tool_routes']), 'approved tool routes required')
        need(isinstance(node['required_evidence'], list) and node['required_evidence'], 'evidence gate cannot be empty')
        for check in node['required_evidence']:
            need(isinstance(check, dict) and set(check) <= {'validator', 'field', 'value'} and {'validator', 'field'} <= set(check), 'invalid evidence check')
            need(check['validator'] in ('equals', 'artifact', 'nonempty_artifact', 'json_success'), 'unregistered evidence validator')
            need(check['field'] in node['output_schema'].get('properties', {}), 'evidence field outside output schema')
            if check['validator'] == 'equals':
                need('value' in check, 'equals value required')
        required_checks = {
            'develop': [('diff_ref', 'nonempty_artifact')],
            'code_test': [('test_results_ref', 'json_success'), ('log_ref', 'nonempty_artifact')],
            'screen_test': [('interaction_results_ref', 'json_success'), ('screenshots_ref', 'nonempty_artifact'), ('trace_ref', 'nonempty_artifact')],
            'visual_review': [('verdicts_ref', 'json_success')],
            'research': [('report_ref', 'nonempty_artifact'), ('claim_verdicts_ref', 'nonempty_artifact')],
            'report': [('report_ref', 'nonempty_artifact')],
        }
        for field, validator in required_checks.get(node['kind'], []):
            need(any(c['field'] == field and c['validator'] == validator for c in node['required_evidence']), 'stage objective evidence requirement missing')
        if node['kind'] == 'code_test':
            need(any(c['field'] == 'exit_code' and c['validator'] == 'equals' and type(c.get('value')) is int and c['value'] == 0 for c in node['required_evidence']), 'test exit code gate required')
        timeout = node.get('timeout_s', policy['stage_timeout_s'])
        need(number(timeout) and 0 < timeout <= policy['stage_timeout_s'], 'node timeout exceeds parent')
        merge_policy(policy, {'retry': node.get('retry_policy', {})})
        if 'quality_policy' in node:
            quality = node['quality_policy']
            need(set(quality) == {'field', 'minimum', 'evaluator_id', 'evaluator_version'} and number(quality['minimum']) and quality['evaluator_id'] and quality['evaluator_version'], 'quality evaluator/version/threshold required')
            need(node['output_schema'].get('properties', {}).get(quality['field'], {}).get('type') in ('integer', 'number'), 'quality field must be numeric output')
    need(isinstance(contract['edges'], list), 'edges list required')
    edge_ids = set()
    for edge in contract['edges']:
        need(set(edge) == {'edge_id', 'from', 'to', 'trigger', 'guards', 'required_inputs', 'required_receipts', 'on_missing', 'on_invalid'}, 'invalid edge fields')
        need(edge['edge_id'] not in edge_ids and edge['from'] in ids and edge['to'] in ids, 'invalid edge identity')
        edge_ids.add(edge['edge_id'])
        need(edge['trigger'] in ('success', 'retry', 'fallback', 'loop'), 'unknown edge trigger')
        need(isinstance(edge['guards'], list) and set(edge['guards']) <= {'receipt_valid', 'budget_remaining', 'same_inputs'}, 'unknown guard')
        need(isinstance(edge['required_inputs'], list) and all(isinstance(x, str) for x in edge['required_inputs']), 'invalid edge inputs')
        need(isinstance(edge['required_receipts'], list) and set(edge['required_receipts']) <= ids, 'invalid receipt dependencies')
        need(edge['on_missing'] == 'awaiting_data' and edge['on_invalid'] == 'failed', 'edge must fail closed')
    pending, done = set(ids), set()
    while pending:
        ready = {n for n in pending if all(e['from'] in done for e in contract['edges'] if e['to'] == n and e['trigger'] == 'success')}
        need(ready, 'success edges must form a DAG; cycles require explicit loop edges')
        pending -= ready
        done |= ready


def bounded_call(invoke, inputs, context, timeout_s, cancelled=None):
    """Supervise a trusted POSIX adapter and its process group, not arbitrary code."""
    if cancelled and cancelled():
        return {'error': 'policy_cancelled'}
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        os.setsid()
        try:
            result = invoke(inputs, context)
            payload = encoded(result)
            if len(payload) > 65536:
                payload = encoded({'error': 'result_too_large'})
        except BaseException as exc:
            payload = encoded({'error': type(exc).__name__})
        try:
            with os.fdopen(write_fd, 'wb') as stream:
                stream.write(payload)
        finally:
            os._exit(0)
    os.close(write_fd)
    end = time.monotonic() + timeout_s
    chunks = bytearray()
    finished = False
    try:
        while True:
            if cancelled and cancelled():
                return {'error': 'policy_cancelled'}
            left = end - time.monotonic()
            if left <= 0:
                return {'error': 'timeout'}
            if not select.select([read_fd], [], [], min(left, 0.05))[0]:
                continue
            data = os.read(read_fd, 65537 - len(chunks))
            if not data:
                finished = True
                break
            chunks.extend(data)
            if len(chunks) > 65536:
                return {'error': 'result_too_large'}
        try:
            result = json.loads(chunks)
            return result if isinstance(result, dict) else {'error': 'malformed_result'}
        except (ValueError, UnicodeError):
            return {'error': 'malformed_result'}
    finally:
        os.close(read_fd)
        if not finished:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                # Child may not yet have created its process group.
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        os.waitpid(pid, 0)


class Runtime:
    def __init__(self, workspace, adapters=None, authority=None, now=None):
        self.workspace = workspace_root(workspace)
        self.root = self.workspace / TASKS
        need(self.root.resolve() == self.root, 'storage symlink forbidden')
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'runtime-v2.sqlite3'
        need(not self.db.is_symlink(), 'database symlink forbidden')
        self.adapters = adapters if adapters is not None else {}
        self.authority = authority
        epoch, monotonic = time.time(), time.monotonic()
        self.now = now or (lambda: epoch + time.monotonic() - monotonic)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS workflows (id INTEGER PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS breakers (route TEXT PRIMARY KEY, failures INTEGER NOT NULL, opened REAL, probe TEXT)')

    @contextmanager
    def connection(self):
        # ponytail: workspace-wide SQLite writer; shard only after measured contention.
        db = sqlite3.connect(self.db, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def task_path(self, ident):
        need(isinstance(ident, str) and re.fullmatch(r'WF-[0-9]{4,}', ident), 'invalid workflow ID')
        path = self.root / ident
        need(path.resolve() == path, 'workflow symlink forbidden')
        return path

    def load(self, db, ident):
        self.task_path(ident)
        row = db.execute('SELECT state FROM workflows WHERE id=?', (int(ident[3:]),)).fetchone()
        need(row, 'unknown workflow')
        return json.loads(row[0])

    def save(self, db, state, event):
        state['revision'] += 1
        state['history'].append({'revision': state['revision'], 'at': self.now(), 'event': event, 'status': state['status']})
        db.execute('UPDATE workflows SET state=? WHERE id=?', (encoded(state).decode(), int(state['id'][3:])))

    def show(self, ident):
        with self.connection() as db:
            return self.load(db, ident)

    def artifact(self, ident, data, media_type='application/json'):
        need(type(data) is bytes and isinstance(media_type, str) and media_type, 'bytes and media type required')
        sha = hashlib.sha256(data).hexdigest()
        directory = self.task_path(ident) / 'artifacts'
        need(directory.resolve() == directory, 'artifact storage symlink forbidden')
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / sha
        need(not path.is_symlink(), 'artifact symlink forbidden')
        try:
            with path.open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except FileExistsError:
            need(path.read_bytes() == data, 'immutable artifact changed')
        return {'uri': 'artifacts/' + sha, 'sha256': sha, 'media_type': media_type, 'bytes': len(data)}

    def read_artifact(self, ident, ref):
        need(isinstance(ref, dict) and set(ref) == {'uri', 'sha256', 'media_type', 'bytes'}, 'invalid ArtifactRef')
        need(type(ref['bytes']) is int and ref['bytes'] >= 0 and isinstance(ref['media_type'], str), 'invalid artifact metadata')
        need(isinstance(ref['sha256'], str) and re.fullmatch('[a-f0-9]{64}', ref['sha256']) and ref['uri'] == 'artifacts/' + ref['sha256'], 'unregistered artifact store/path')
        path = self.task_path(ident) / ref['uri']
        need(path.resolve() == path, 'artifact symlink forbidden')
        data = path.read_bytes()
        need(len(data) == ref['bytes'] and hashlib.sha256(data).hexdigest() == ref['sha256'], 'artifact integrity failure')
        return data

    def binding(self, state, inputs=None):
        return {'workflow_id': state['id'], 'contract_version': state['contract_version'], 'plan_version': state['plan_version'],
                'policy_version': state['policy_version'], 'input_digest': digest(inputs), 'code_fingerprint': snapshot(self.workspace)}

    def account(self, state):
        if state['status'] == 'failed':
            return False
        now = self.now()
        try:
            tick(state['clock'], now)
            for node in state['nodes'].values():
                if node['clock'] is not None and node['status'] != 'done':
                    tick(node['clock'], now)
        except ValueError:
            state.update(status='awaiting_data', reason='clock_inconsistent')
            return False
        policy = state['policy']
        if remaining(state['clock'], policy['workflow_timeout_s']) <= 0:
            state.update(status='failed', reason='workflow_timeout')
            return False
        if state['usage']['tokens'] >= policy['max_tokens'] or state['usage']['cost_microusd'] >= policy['max_cost_microusd']:
            state.update(status='failed', reason='budget_exhausted')
            return False
        return True

    def verify_refs(self, ident, value):
        if isinstance(value, dict):
            if set(value) == {'uri', 'sha256', 'media_type', 'bytes'}:
                self.read_artifact(ident, value)
            else:
                for item in value.values():
                    self.verify_refs(ident, item)
        elif isinstance(value, list):
            for item in value:
                self.verify_refs(ident, item)

    def verify_checkpoint(self, state):
        approvals = {a['approval_id']: a for a in state['approvals']}
        for approval in approvals.values():
            self.read_artifact(state['id'], approval['auth_evidence_ref'])
        for attempt in state['attempts']:
            if attempt.get('approval_id'):
                need(attempt['approval_id'] in approvals and approvals[attempt['approval_id']]['decision'] == 'approve', 'attempt approval record missing')
        if state['checkpoint']:
            last = json.loads(self.read_artifact(state['id'], state['checkpoint']))
            need(last['code_fingerprint'] == snapshot(self.workspace), 'code changed since checkpoint')

    def hil_clock(self, clock, waiting):
        if (clock['waiting_since'] is not None) != waiting:
            set_hil(clock, self.now(), waiting)

    def request(self, state, kind, payload, node_id=None):
        need(state['pending_approval'] is None, 'settle pending approval first')
        now = self.now()
        request = {'kind': kind, 'payload': payload, 'node_id': node_id, 'version_binding': self.binding(state, payload),
                   'issued_at': now, 'expires_at': now + state['policy']['approval_timeout_s']}
        request['action_digest'] = digest(request)
        request['delivered'] = False
        if self.authority is not None:
            try:
                request['delivered'] = self.authority.deliver(copy.deepcopy(request)) is True
            except Exception:
                pass
        state['pending_approval'] = request
        state.update(status='awaiting_data', reason='human_approval_required')
        if request['delivered']:
            if node_id and state['nodes'][node_id]['clock'] is not None:
                self.hil_clock(state['nodes'][node_id]['clock'], True)
            if not any(n['status'] == 'running' for n in state['nodes'].values()):
                self.hil_clock(state['clock'], True)
                if node_id is None:
                    for item in state['nodes'].values():
                        if item['clock'] and item['status'] != 'done':
                            self.hil_clock(item['clock'], True)

    def create(self, contract, policy=None):
        policy = merge_policy(DEFAULTS, policy or {})
        validate_contract(contract, policy)
        now = self.now()
        with self.connection() as db:
            cursor = db.execute("INSERT INTO workflows(state) VALUES ('{}')")
            ident = f'WF-{cursor.lastrowid:04d}'
            self.task_path(ident).mkdir(exist_ok=False)
            state = {'schema': 2, 'id': ident, 'revision': 0, 'status': 'awaiting_data', 'reason': 'contract_approval_required',
                     'contract': copy.deepcopy(contract), 'contract_version': 1, 'plan_version': 1, 'policy': policy, 'policy_version': 1,
                     'policy_history': [], 'clock': new_clock(now), 'nodes': {}, 'attempts': [], 'receipts': [], 'history': [],
                     'usage': {'tokens': 0, 'cost_microusd': 0}, 'reservations': {}, 'loop_iterations': 0, 'tool_retries': 0,
                     'pending_approval': None, 'contract_approved': False, 'action_approval': None, 'approvals': [], 'checkpoint': None}
            state['nodes'] = {n['node_id']: {'status': 'pending', 'clock': None, 'attempts': 0, 'receipt': None, 'not_before': 0, 'route_index': 0} for n in contract['nodes']}
            self.request(state, 'contract', {'contract_digest': digest(contract), 'policy': policy})
            self.save(db, state, 'create')
            return state

    def request_tuning(self, ident, expected, patch, reason):
        with self.connection() as db:
            state = self.load(db, ident)
            need(state['revision'] == expected, 'revision conflict')
            need(state['status'] not in ('failed', 'completed'), 'terminal workflow')
            need(isinstance(reason, str) and reason.strip(), 'tuning reason required')
            need(not state['reservations'] and not any(n['status'] == 'running' for n in state['nodes'].values()), 'settle calls and reservations before tuning')
            policy = merge_policy(state['policy'], patch)
            validate_contract(state['contract'], policy)
            if self.account(state):
                self.request(state, 'policy', {'policy': policy, 'reason': reason})
            self.save(db, state, 'request_tuning')
            return state

    def approve(self, ident, expected, proof):
        with self.connection() as db:
            state = self.load(db, ident)
            need(state['revision'] == expected, 'revision conflict')
            request = state['pending_approval']
            need(request is not None and self.authority is not None, 'no authenticated approval adapter/request')
            principal = self.authority.verify(copy.deepcopy(proof), copy.deepcopy(request))
            need(principal in state['contract']['approvers'], 'unauthenticated or unauthorized principal')
            need(request['version_binding'] == self.binding(state, request['payload']), 'approval binding changed')
            self.account(state)
            now = self.now()
            self.hil_clock(state['clock'], False)
            node_id = request['node_id']
            if node_id and state['nodes'][node_id]['clock'] is not None:
                self.hil_clock(state['nodes'][node_id]['clock'], False)
            if node_id is None:
                for item in state['nodes'].values():
                    if item['clock']:
                        self.hil_clock(item['clock'], False)
            state['pending_approval'] = None
            if state['status'] == 'failed':
                pass
            elif now >= request['expires_at']:
                self.approval_failure(state, request, 'approval_expired_default_deny')
            else:
                approval = self.approval_record(state, request, principal, proof, 'approve')
                state['approvals'].append(approval)
                kind = request['kind']
                if kind == 'contract':
                    state['contract_approved'] = True
                elif kind == 'policy':
                    state['policy_history'].append({'version': state['policy_version'] + 1, 'before': state['policy'], 'after': request['payload']['policy'],
                                                    'reason': request['payload']['reason'], 'approver_id': principal, 'request': request})
                    state['policy'] = request['payload']['policy']
                    state['policy_version'] += 1
                    state['action_approval'] = None
                elif kind == 'action':
                    state['action_approval'] = {'payload': request['payload'], 'expires_at': request['expires_at'], 'policy_version': state['policy_version'], 'approver_id': principal, 'approval_id': approval['approval_id']}
                elif kind == 'quality':
                    # Approval to reassess never turns failed evidence into a pass.
                    state['nodes'][node_id]['status'] = 'failed'
                state.update(status='ready', reason='approved')
                self.account(state)
            self.save(db, state, {'approve': request['action_digest'], 'principal': principal})
            return state

    def approval_record(self, state, request, principal, proof, decision):
        # Keep credentials out of state; the trusted authority's attestation is the
        # evidence, not an invented claim that a digest authenticates the human.
        evidence = {'principal_id': principal, 'authority': type(self.authority).__name__, 'verified': True,
                    'request_digest': request['action_digest'], 'proof_digest': digest(proof), 'observed_at': self.now()}
        return {'approval_id': f"APPROVAL-{len(state['approvals']) + 1:04d}", 'approver_id': principal,
                'action_digest': request['action_digest'], 'version_binding': request['version_binding'], 'issued_at': request['issued_at'],
                'expires_at': request['expires_at'], 'decision': decision, 'single_use': True,
                'auth_evidence_ref': self.artifact(state['id'], encoded(evidence))}

    def approval_failure(self, state, request, reason):
        if request['node_id']:
            node_id = request['node_id']
            attempt = {'attempt_id': f"{node_id}/approval-{state['revision']}", 'node_id': node_id, 'started_at': request['issued_at']}
            state['attempts'].append(attempt)
            self.fail_attempt(state, attempt, reason)
        else:
            state.update(status='failed', reason=reason)

    def deny(self, ident, expected, proof):
        with self.connection() as db:
            state = self.load(db, ident)
            need(expected == state['revision'], 'revision conflict')
            request = state['pending_approval']
            need(request and self.authority, 'no approval request/authority')
            principal = self.authority.verify(copy.deepcopy(proof), copy.deepcopy(request))
            need(principal in state['contract']['approvers'], 'unauthenticated principal')
            self.account(state)
            state['approvals'].append(self.approval_record(state, request, principal, proof, 'deny'))
            self.hil_clock(state['clock'], False)
            for item in state['nodes'].values():
                if item['clock']:
                    self.hil_clock(item['clock'], False)
            state['pending_approval'] = None
            self.approval_failure(state, request, 'human_denied')
            self.save(db, state, {'deny': request['action_digest'], 'principal': principal})
            return state

    def evidence(self, ident, node, outputs):
        results = []
        for check in node['required_evidence']:
            value = outputs.get(check['field'])
            status = 'pass'
            refs = []
            try:
                if check['field'] not in outputs:
                    status = 'missing'
                elif check['validator'] == 'equals':
                    status = 'pass' if type(value) is type(check['value']) and value == check['value'] else 'fail'
                else:
                    data = self.read_artifact(ident, value)
                    refs = [value]
                    if check['validator'] == 'nonempty_artifact' and not data.strip():
                        status = 'fail'
                    if check['validator'] == 'json_success':
                        result = json.loads(data)
                        status = 'pass' if all(type(result.get(k)) is int and result[k] == 0 for k in ('exit_code', 'failed', 'fatal_errors')) and type(result.get('passed')) is int and result['passed'] > 0 else 'fail'
            except FileNotFoundError:
                status = 'missing'
            except (ValueError, TypeError, OSError, AttributeError):
                status = 'error'
            results.append({'check_id': check['field'], 'validator_id': check['validator'], 'validator_version': '1', 'status': status,
                            'subject_digest': digest(outputs), 'evidence_refs': refs, 'observed_at': self.now()})
        return results

    def fail_attempt(self, state, attempt, reason, recoverable=False):
        attempt.update(status='failed', reason=reason, finished_at=self.now())
        node_id = attempt['node_id']
        node = state['nodes'][node_id]
        node['status'] = 'failed'
        # Failed verification needs new work, not a transport retry or a terminal
        # workflow failure. Only an explicit loop may authorize the next attempt.
        if (state['status'] != 'failed' and reason == 'evidence_gate_failed'
                and self.node_contract(state, node_id)['kind'] in ('code_test', 'screen_test', 'visual_review', 'evidence_gate')):
            has_loop = any(e['from'] == node_id and e['trigger'] == 'loop' for e in state['contract']['edges'])
            state.update(status='ready' if has_loop else 'awaiting_data', reason='rework_required')
            return
        edges = [e for e in state['contract']['edges'] if e['from'] == node_id and e['trigger'] in ('retry', 'fallback')]
        if recoverable and edges:
            policy = merge_policy(state['policy'], {'retry': self.node_contract(state, node_id).get('retry_policy', {})})
            retry = policy['retry']
            if node['attempts'] < retry['max_attempts'] and state['tool_retries'] < policy['max_tool_retries'] and node['clock']['consumed_s'] < retry['max_elapsed_s']:
                node['not_before'] = self.now() + retry_delay(policy, node['attempts'], random.random())
                routes = self.node_contract(state, node_id)['tool_routes']
                if any(e['trigger'] == 'fallback' for e in edges) and attempt.get('route') in routes:
                    node['route_index'] = min(routes.index(attempt['route']) + 1, len(routes) - 1)
                state.update(status='ready', reason='retry_edge')
                return
        state.update(status='failed', reason=reason)

    def node_contract(self, state, node_id):
        return next(n for n in state['contract']['nodes'] if n['node_id'] == node_id)

    def before_tool_call(self, db, state, node_id, inputs):
        """Only this gate can reserve usage and produce a runnable attempt."""
        if state['status'] in ('failed', 'completed') or not self.account(state):
            return None
        if not state['contract_approved']:
            state.update(status='awaiting_data', reason='contract_approval_required')
            return None
        try:
            self.verify_refs(state['id'], inputs)
            self.verify_checkpoint(state)
        except (ValueError, OSError):
            state.update(status='awaiting_data', reason='input_or_checkpoint_evidence_changed')
            return None
        node = self.node_contract(state, node_id)
        current = state['nodes'][node_id]
        if current['status'] == 'failed':
            previous = next(a for a in reversed(state['attempts']) if a['node_id'] == node_id)
            if previous.get('reason') == 'evidence_gate_failed':
                state.update(status='awaiting_data', reason='rework_required')
                return None
        if current['status'] in ('done', 'running', 'unknown', 'awaiting_data') or any(a['status'] == 'unknown' for a in state['attempts']):
            state.update(status='awaiting_data', reason='unsettled_or_completed_attempt')
            return None
        if state['pending_approval'] is not None:
            pending = state['pending_approval']
            if pending['node_id'] in (None, node_id):
                return None
        for edge in state['contract']['edges']:
            if edge['to'] != node_id or edge['trigger'] != 'success':
                continue
            for dependency in {edge['from'], *edge['required_receipts']}:
                receipt = state['nodes'][dependency]['receipt']
                if not receipt:
                    state.update(status='awaiting_data', reason='required_receipt_missing')
                    return None
                try:
                    evidence = json.loads(self.read_artifact(state['id'], receipt))
                    for ref in evidence['input_refs'] + evidence['output_refs']:
                        self.verify_refs(state['id'], json.loads(self.read_artifact(state['id'], ref)))
                    if 'same_inputs' in edge['guards'] and evidence['version_binding']['input_digest'] != digest(inputs):
                        state.update(status='failed', reason='edge_same_inputs_failed')
                        return None
                except (ValueError, OSError):
                    state.update(status='awaiting_data', reason='required_receipt_invalid')
                    return None
            if not set(edge['required_inputs']) <= set(inputs):
                state.update(status='awaiting_data', reason='edge_inputs_missing')
                return None
        status, problems = schema_check(inputs, node['input_schema'])
        if status == 'missing':
            state.update(status='awaiting_data', reason='inputs_missing', missing=problems)
            return None
        if current['clock'] is None:
            current['clock'] = new_clock(self.now())
        if status == 'invalid':
            attempt = {'attempt_id': f"{node_id}/attempt-{current['attempts'] + 1}", 'node_id': node_id, 'started_at': self.now()}
            current['attempts'] += 1
            state['attempts'].append(attempt)
            self.fail_attempt(state, attempt, 'invalid_inputs')
            return None
        policy = merge_policy(state['policy'], {'retry': node.get('retry_policy', {})})
        if current['attempts'] >= policy['retry']['max_attempts'] or (current['attempts'] and state['tool_retries'] >= policy['max_tool_retries']):
            state.update(status='failed', reason='retry_budget_exhausted')
            return None
        if current['attempts'] and current['clock']['consumed_s'] >= policy['retry']['max_elapsed_s']:
            state.update(status='failed', reason='retry_timeout')
            return None
        if self.now() < current['not_before']:
            state.update(status='awaiting_data', reason='backoff')
            return None
        if current['attempts'] and not any(e['from'] == node_id and e['to'] == node_id and e['trigger'] in ('retry', 'fallback') for e in state['contract']['edges']):
            if not current.get('loop_authorized', False):
                state.update(status='failed', reason='retry_edge_missing')
                return None
        if current['attempts'] and current['status'] == 'failed':
            previous = next(a for a in reversed(state['attempts']) if a['node_id'] == node_id)
            if previous.get('version_binding', {}).get('input_digest') != digest(inputs):
                state.update(status='awaiting_data', reason='retry_inputs_changed')
                return None
        chosen = None
        if current['route_index'] == 0 and node['tool_routes'][0] not in self.adapters:
            state.update(status='awaiting_data', reason='primary_adapter_missing')
            return None
        for route in node['tool_routes'][current['route_index']:]:
            adapter = self.adapters.get(route)
            if adapter is None:
                continue
            breaker = db.execute('SELECT failures,opened,probe FROM breakers WHERE route=?', (route,)).fetchone()
            if breaker and breaker[1] is not None and (self.now() < breaker[1] + policy['breaker']['cooldown_s'] or breaker[2] is not None):
                continue
            if route != node['tool_routes'][0] and not any(e['from'] == node_id and e['to'] == node_id and e['trigger'] == 'fallback' for e in state['contract']['edges']):
                continue
            chosen = route, adapter, breaker
            break
        if chosen is None:
            state.update(status='awaiting_data', reason='adapter_missing_or_circuit_open')
            return None
        route, adapter, breaker = chosen
        if adapter.get('actor') != node['actor'] or adapter.get('bounded') is not True or adapter.get('cancellable') is not True:
            state.update(status='awaiting_data', reason='adapter_capability_missing')
            return None
        if type(adapter.get('tier')) is not int or adapter['tier'] not in (1, 2, 3) or not callable(adapter.get('allowed')) or adapter['allowed'](copy.deepcopy(inputs)) is not True:
            state.update(status='failed', reason='tool_policy_denied')
            return None
        if any(type(adapter.get(k)) is not int or adapter[k] < 0 for k in ('max_tokens', 'max_cost_microusd')) or not adapter.get('meter_id') or not adapter.get('price_version'):
            state.update(status='awaiting_data', reason='usage_bound_unknown')
            return None
        if current['attempts'] and adapter.get('idempotent') is not True:
            state.update(status='failed', reason='non_idempotent_retry_denied')
            return None
        action = {'route': route, 'inputs_digest': digest(inputs), 'node_id': node_id, 'max_tokens': adapter['max_tokens'], 'max_cost_microusd': adapter['max_cost_microusd'], 'binding': self.binding(state, inputs)}
        if adapter['tier'] == 3 or node['actor']['kind'] == 'human':
            approval = state['action_approval']
            if not approval or approval['payload'] != action or approval['policy_version'] != state['policy_version'] or self.now() >= approval['expires_at']:
                state['action_approval'] = None
                self.request(state, 'action', action, node_id)
                return None
        tokens = state['usage']['tokens'] + sum(r['tokens'] for r in state['reservations'].values())
        cost = state['usage']['cost_microusd'] + sum(r['cost_microusd'] for r in state['reservations'].values())
        if tokens + adapter['max_tokens'] > policy['max_tokens'] or cost + adapter['max_cost_microusd'] > policy['max_cost_microusd']:
            state.update(status='awaiting_data' if state['reservations'] else 'failed', reason='budget_reserved' if state['reservations'] else 'budget_exhausted')
            return None
        if not self.account(state):
            return None
        timeout = min(policy['tool_timeout_s'], remaining(current['clock'], node.get('timeout_s', policy['stage_timeout_s'])), remaining(state['clock'], policy['workflow_timeout_s']))
        if current['attempts']:
            timeout = min(timeout, remaining(current['clock'], policy['retry']['max_elapsed_s']))
        if timeout <= 0:
            state.update(status='failed', reason='stage_timeout')
            return None
        self.hil_clock(state['clock'], False)
        self.hil_clock(current['clock'], False)
        current.pop('loop_authorized', None)
        current['attempts'] += 1
        if current['attempts'] > 1:
            state['tool_retries'] += 1
        ident = f"{node_id}/attempt-{current['attempts']}"
        attempt = {'attempt_id': ident, 'node_id': node_id, 'status': 'running', 'route': route, 'actor': adapter['actor'], 'version_binding': self.binding(state, inputs),
                   'started_at': self.now(), 'timeout_s': timeout, 'input_ref': self.artifact(state['id'], encoded(inputs)),
                   'intent': {'idempotency_key': state['id'] + '/' + ident, 'action': action} if adapter['tier'] == 3 else None}
        if state['action_approval']:
            attempt['approval_id'] = state['action_approval']['approval_id']
        state['attempts'].append(attempt)
        state['reservations'][ident] = {'tokens': adapter['max_tokens'], 'cost_microusd': adapter['max_cost_microusd']}
        if breaker and breaker[1] is not None:
            db.execute('UPDATE breakers SET probe=? WHERE route=?', (state['id'] + '/' + ident, route))
        state['action_approval'] = None
        current['status'] = 'running'
        state.update(status='running', reason='executing')
        return attempt, adapter

    def execute(self, ident, node_id, inputs):
        need(isinstance(inputs, dict), 'inputs must be an object')
        with self.connection() as db:
            state = self.load(db, ident)
            need(node_id in state['nodes'], 'unknown node')
            prepared = self.before_tool_call(db, state, node_id, inputs)
            self.save(db, state, {'before_tool_call': node_id})
        if prepared is None:
            return state
        attempt, adapter = prepared
        result = bounded_call(adapter['invoke'], copy.deepcopy(inputs), {'workspace': str(self.workspace), 'task': str(self.task_path(ident)), 'intent': attempt['intent']}, attempt['timeout_s'], cancelled=lambda: self.cancelled(ident))
        with self.connection() as db:
            state = self.load(db, ident)
            attempt = next(a for a in state['attempts'] if a['attempt_id'] == attempt['attempt_id'])
            need(attempt['status'] == 'running', 'attempt no longer active')
            self.settle(db, state, attempt, adapter, result)
            pending = state['pending_approval']
            if pending and pending['delivered'] and not any(n['status'] == 'running' for n in state['nodes'].values()):
                self.hil_clock(state['clock'], True)
            self.save(db, state, {'settle': attempt['attempt_id']})
        return state

    def cancelled(self, ident):
        try:
            with closing(sqlite3.connect(self.db, timeout=0.1)) as db:
                state = self.load(db, ident)
                return state['status'] == 'failed'
        except (ValueError, OSError, sqlite3.Error):
            return True  # Losing the policy authority cannot authorize continuing.

    def reconcile(self, ident, node_id):
        """Query a registered nonbillable reconciliation adapter; never re-invoke intent."""
        with self.connection() as db:
            state = self.load(db, ident)
            attempt = next(a for a in reversed(state['attempts']) if a['node_id'] == node_id)
            need(attempt['status'] == 'unknown', 'only unknown attempts need usage reconciliation')
            adapter = self.adapters.get(attempt['route'], {})
            if not callable(adapter.get('reconcile')):
                state.update(status='awaiting_data', reason='reconciliation_adapter_missing')
                self.save(db, state, 'reconcile_blocked')
                return state
            if not self.account(state):
                self.save(db, state, 'reconcile_budget_check')
                return state
            timeout = min(state['policy']['tool_timeout_s'], remaining(state['clock'], state['policy']['workflow_timeout_s']))
            attempt['status'] = 'reconciling'
            self.save(db, state, 'reconcile_intent')
        result = bounded_call(adapter['reconcile'], copy.deepcopy(attempt), {'workspace': str(self.workspace), 'task': str(self.task_path(ident))}, timeout)
        with self.connection() as db:
            state = self.load(db, ident)
            attempt = next(a for a in state['attempts'] if a['attempt_id'] == attempt['attempt_id'])
            need(attempt['status'] == 'reconciling', 'reconciliation no longer active')
            self.settle(db, state, attempt, adapter, result)
            self.save(db, state, 'reconcile_result')
            return state

    def loop(self, ident, edge_id, reason):
        with self.connection() as db:
            state = self.load(db, ident)
            need(isinstance(reason, str) and reason.strip(), 'loop reason required')
            need(state['status'] not in ('failed', 'completed') and not state['reservations'] and state['pending_approval'] is None, 'loop blocked by terminal/unsettled state')
            edge = next((e for e in state['contract']['edges'] if e['edge_id'] == edge_id and e['trigger'] == 'loop'), None)
            need(edge, 'explicit loop edge required')
            if not self.account(state):
                self.save(db, state, 'loop_budget_check')
                return state
            if state['loop_iterations'] >= state['policy']['max_loop_iterations']:
                state.update(status='failed', reason='loop_budget_exhausted')
            else:
                state['loop_iterations'] += 1
                affected = {edge['to']}
                while True:
                    more = {e['to'] for e in state['contract']['edges'] if e['trigger'] == 'success' and e['from'] in affected}
                    if more <= affected:
                        break
                    affected |= more
                for node_id in affected:
                    state['nodes'][node_id].update(status='pending', receipt=None, loop_authorized=True)
                state['action_approval'] = None
                state['checkpoint'] = None
                state.update(status='ready', reason='loop_edge')
            self.save(db, state, {'loop': edge_id, 'reason': reason})
            return state

    def settle(self, db, state, attempt, adapter, result):
        node_id = attempt['node_id']
        node = self.node_contract(state, node_id)
        current = state['nodes'][node_id]
        alive = self.account(state)
        usage = result.get('usage')
        fields = {'input_tokens', 'output_tokens', 'other_billable_tokens', 'cost_microusd', 'meter_id', 'price_version'}
        known = isinstance(usage, dict) and set(usage) == fields and all(type(usage[k]) is int and usage[k] >= 0 for k in fields - {'meter_id', 'price_version'}) and usage['meter_id'] == adapter['meter_id'] and usage['price_version'] == adapter['price_version']
        if not known:
            self.record_outage(db, state, attempt, result.get('error'))
            attempt.update(status='unknown', reason=result.get('error', 'usage_unknown'), finished_at=self.now())
            current['status'] = 'unknown'
            if alive:
                state.update(status='awaiting_data', reason='usage_or_outcome_unknown')
            return
        used_tokens = usage['input_tokens'] + usage['output_tokens'] + usage['other_billable_tokens']
        reservation = state['reservations'][attempt['attempt_id']]
        state['usage']['tokens'] += used_tokens
        state['usage']['cost_microusd'] += usage['cost_microusd']
        attempt['usage'] = usage
        del state['reservations'][attempt['attempt_id']]
        if used_tokens > reservation['tokens'] or usage['cost_microusd'] > reservation['cost_microusd']:
            self.fail_attempt(state, attempt, 'adapter_exceeded_reservation')
            return
        if not alive:
            self.fail_attempt(state, attempt, state['reason'])
            return
        if result.get('error'):
            self.record_outage(db, state, attempt, result['error'])
            self.fail_attempt(state, attempt, str(result['error']), recoverable=result['error'] in RETRYABLE_ERRORS and adapter.get('idempotent') is True and attempt['intent'] is None)
            return
        db.execute('INSERT OR REPLACE INTO breakers VALUES (?,0,NULL,NULL)', (attempt['route'],))
        outputs = result.get('outputs')
        status, problems = schema_check(outputs, node['output_schema'])
        if status != 'pass':
            if status == 'missing':
                attempt.update(status='awaiting_data', reason='output_missing', finished_at=self.now())
                current['status'] = 'awaiting_data'
                state.update(status='awaiting_data', reason='output_missing', missing=problems)
            else:
                self.fail_attempt(state, attempt, 'invalid_outputs')
            return
        inputs = json.loads(self.read_artifact(state['id'], attempt['input_ref']))
        if node['kind'] == 'research' and inputs['required'] and outputs['status'] != 'answered':
            self.fail_attempt(state, attempt, 'required_research_unresolved')
            return
        if node['actor']['kind'] == 'human':
            approved = next((a for a in state['approvals'] if a['approval_id'] == attempt.get('approval_id')), None)
            if outputs.get('approval') != approved or approved is None:
                self.fail_attempt(state, attempt, 'human_output_approval_mismatch')
                return
        try:
            self.verify_refs(state['id'], outputs)
        except (ValueError, OSError):
            attempt.update(status='awaiting_data', reason='output_artifact_missing_or_changed', finished_at=self.now())
            current['status'] = 'awaiting_data'
            state.update(status='awaiting_data', reason='output_artifact_missing_or_changed')
            return
        results = self.evidence(state['id'], node, outputs)
        attempt['evidence_results'] = results
        if any(r['status'] != 'pass' for r in results):
            if any(r['status'] == 'missing' for r in results):
                attempt.update(status='awaiting_data', reason='evidence_missing', finished_at=self.now())
                current['status'] = 'awaiting_data'
                state.update(status='awaiting_data', reason='evidence_missing')
            else:
                self.fail_attempt(state, attempt, 'evidence_gate_failed')
            return
        quality = node.get('quality_policy')
        if quality and (not number(outputs.get(quality['field'])) or outputs[quality['field']] < quality['minimum']):
            attempt.update(status='failed', reason='quality_below_threshold', finished_at=self.now())
            current['status'] = 'failed'
            self.request(state, 'quality', {'attempt_id': attempt['attempt_id'], 'quality_policy': quality}, node_id)
            return
        output_ref = self.artifact(state['id'], encoded(outputs))
        receipt = {'receipt_id': f"RECEIPT-{len(state['receipts']) + 1:04d}", 'node_id': node_id, 'attempt_id': attempt['attempt_id'],
                   'actor': attempt['actor'], 'version_binding': attempt['version_binding'], 'input_refs': [attempt['input_ref']], 'output_refs': [output_ref],
                   'evidence_results': results, 'usage': usage, 'started_at': attempt['started_at'], 'finished_at': self.now(), 'commit_seq': state['revision'] + 1,
                   'code_fingerprint': snapshot(self.workspace)}
        ref = self.artifact(state['id'], encoded(receipt))
        attempt.update(status='done', finished_at=self.now(), receipt=ref)
        current.update(status='done', receipt=ref)
        state['receipts'].append(ref)
        state['checkpoint'] = ref
        state.update(status='completed' if all(n['status'] == 'done' for n in state['nodes'].values()) else 'ready', reason='receipt_committed')
        if state['status'] == 'completed':
            state['report_ref'] = self.artifact(state['id'], self.render_report(state).encode(), 'text/markdown')

    def record_outage(self, db, state, attempt, error):
        if not isinstance(error, str) or error not in RETRYABLE_ERRORS or attempt.get('breaker_recorded'):
            return
        row = db.execute('SELECT failures FROM breakers WHERE route=?', (attempt['route'],)).fetchone()
        failures = (row[0] if row else 0) + 1
        opened = self.now() if failures >= state['policy']['breaker']['failure_threshold'] else None
        db.execute('INSERT OR REPLACE INTO breakers VALUES (?,?,?,NULL)', (attempt['route'], failures, opened))
        attempt['breaker_recorded'] = True

    def resume(self, ident):
        with self.connection() as db:
            state = self.load(db, ident)
            if state['status'] != 'completed' and not self.account(state):
                self.save(db, state, 'resume_budget_check')
                return state
            try:
                self.verify_checkpoint(state)
                for ref in state['receipts']:
                    receipt = json.loads(self.read_artifact(ident, ref))
                    for artifact in receipt['input_refs'] + receipt['output_refs']:
                        self.read_artifact(ident, artifact)
                    for result in receipt['evidence_results']:
                        for artifact in result['evidence_refs']:
                            self.read_artifact(ident, artifact)
                if state['checkpoint']:
                    last = json.loads(self.read_artifact(ident, state['checkpoint']))
                    need(last['code_fingerprint'] == snapshot(self.workspace), 'code changed since checkpoint')
            except (ValueError, OSError, KeyError):
                state.update(status='awaiting_data', reason='checkpoint_evidence_changed')
            if state['reservations']:
                for attempt in state['attempts']:
                    if attempt['status'] in ('running', 'reconciling') and self.now() >= attempt['started_at'] + attempt['timeout_s']:
                        attempt.update(status='unknown', reason='supervisor_deadline_elapsed', finished_at=self.now())
                        state['nodes'][attempt['node_id']]['status'] = 'unknown'
                state.update(status='awaiting_data', reason='unreconciled_intent_or_usage')
            self.save(db, state, 'resume')
            return state

    def report(self, ident):
        state = self.resume(ident)
        path = self.task_path(ident) / 'report.md'
        atomic_write(path, self.render_report(state))
        return path

    def render_report(self, state):
        ident = state['id']
        lines = [f"# {ident}: {state['contract']['title']}", '', f"Status: {state['status']} (revision {state['revision']})", '',
                 f"Reason: {state['reason']}", f"Policy version: {state['policy_version']}",
                 f"Execution seconds: {state['clock']['consumed_s']}", f"Usage: {json.dumps(state['usage'])}",
                 f"Unsettled reservations: {len(state['reservations'])}", '', '## Receipts', '']
        lines += [f"- [{ref['sha256']}]({ref['uri']})" for ref in state['receipts']]
        lines += ['', '## Attempts', '']
        lines += [f"- {a['attempt_id']}: {a['status']}; route {a.get('route', 'approval')}; reason {a.get('reason', 'verified')}" for a in state['attempts']]
        lines += ['', '## Policy changes', '', json.dumps(state['policy_history'], ensure_ascii=False, indent=2)]
        lines += ['', '## Limits', '', 'Trusted registered adapters only. Native provider hooks and human identity integration are not installed.',
                  'The SQLite state is authoritative; this report is a derived snapshot.', '']
        return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['defaults', 'init', 'show', 'resume', 'report'])
    parser.add_argument('--workspace')
    parser.add_argument('--workflow')
    parser.add_argument('--contract')
    parser.add_argument('--policy')
    args = parser.parse_args()
    try:
        if args.command == 'defaults':
            output = DEFAULTS
        else:
            need(args.workspace, '--workspace required')
            runtime = Runtime(args.workspace)
            if args.command == 'init':
                need(args.contract, '--contract required')
                output = runtime.create(json.loads(Path(args.contract).read_text()), json.loads(Path(args.policy).read_text()) if args.policy else {})
            else:
                need(args.workflow, '--workflow required')
                output = getattr(runtime, args.command)(args.workflow)
                if isinstance(output, Path):
                    output = str(output)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'graph-runtime: {exc}\n')


if __name__ == '__main__':
    main()
