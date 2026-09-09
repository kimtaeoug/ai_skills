#!/usr/bin/env python3
"""Pure policy and execution-clock helpers for task-orchestrator v2."""
import copy
import math


DEFAULTS = {
    'workflow_timeout_s': 3600,
    'stage_timeout_s': 900,
    'tool_timeout_s': 120,
    'approval_timeout_s': 600,
    'retry': {
        'max_attempts': 3,
        'base_delay_s': 1,
        'cap_delay_s': 30,
        'max_elapsed_s': 180,
    },
    'breaker': {
        'failure_threshold': 3,
        'cooldown_s': 60,
    },
    'max_loop_iterations': 10,
    'max_tool_retries': 20,
    'max_tokens': 100000,
    'max_cost_microusd': 5000000,
    'unknown_usage_policy': 'awaiting_data',
    'approval_default': 'deny',
}

_NESTED = {'retry', 'breaker'}
_INTEGER = {
    'retry.max_attempts',
    'breaker.failure_threshold',
    'max_loop_iterations',
    'max_tool_retries',
    'max_tokens',
    'max_cost_microusd',
}
_POSITIVE = {
    'workflow_timeout_s',
    'stage_timeout_s',
    'tool_timeout_s',
    'approval_timeout_s',
    'retry.max_attempts',
    'breaker.failure_threshold',
}
_SAFETY = {
    'unknown_usage_policy': 'awaiting_data',
    'approval_default': 'deny',
}


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _number(name, value):
    _need(not isinstance(value, bool), f'{name} must be numeric')
    if name in _INTEGER:
        _need(type(value) is int, f'{name} must be an integer')
    else:
        _need(isinstance(value, (int, float)), f'{name} must be numeric')
    _need(math.isfinite(value), f'{name} must be finite')
    _need(value >= 0, f'{name} must be nonnegative')
    if name in _POSITIVE:
        _need(value > 0, f'{name} must be positive')
    return value


def _validate(policy):
    _need(isinstance(policy, dict), 'policy must be a dict')
    _need(set(policy) == set(DEFAULTS), 'unknown or missing policy key')
    for key, default in DEFAULTS.items():
        value = policy[key]
        if key in _SAFETY:
            _need(value == default, f'{key} cannot be changed')
        elif key in _NESTED:
            _need(isinstance(value, dict), f'{key} must be a dict')
            _need(set(value) == set(default), f'unknown or missing {key} key')
            for child in value:
                _number(f'{key}.{child}', value[child])
        else:
            _number(key, value)
    _need(policy['tool_timeout_s'] <= policy['stage_timeout_s'] <= policy['workflow_timeout_s'],
          'invalid hierarchy: tool_timeout_s <= stage_timeout_s <= workflow_timeout_s required')
    _need(policy['retry']['max_elapsed_s'] <= policy['stage_timeout_s'],
          'invalid hierarchy: retry.max_elapsed_s <= stage_timeout_s required')
    _need(policy['retry']['base_delay_s'] <= policy['retry']['cap_delay_s'],
          'invalid hierarchy: retry.base_delay_s <= retry.cap_delay_s required')
    return policy


def _check_patch(patch, defaults=DEFAULTS, prefix=''):
    _need(isinstance(patch, dict), 'policy patch must be a dict')
    for key, value in patch.items():
        name = f'{prefix}.{key}' if prefix else key
        _need(key in defaults, f'unknown policy key: {name}')
        if key in _SAFETY:
            _need(value == defaults[key], f'{key} cannot be changed')
        elif key in _NESTED:
            _need(isinstance(value, dict), f'{name} must be a dict')
            _check_patch(value, defaults[key], name)
        elif isinstance(defaults[key], dict):
            _need(False, f'{name} must be a dict')
        else:
            _number(name, value)


def merge_policy(current, patch):
    """Return a validated copy of current with a strict partial patch applied."""
    base = copy.deepcopy(_validate(copy.deepcopy(current)))
    _check_patch(patch)
    for key, value in patch.items():
        if key in _NESTED:
            base[key].update(value)
        else:
            base[key] = value
    return copy.deepcopy(_validate(base))


def _time(value):
    _need(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value),
          'time must be finite')
    return value


def new_clock(now):
    now = _time(now)
    return {
        'consumed_s': 0,
        'last_accounted_at': now,
        'hil_wait_intervals': [],
        'waiting_since': None,
    }


def tick(clock, now):
    now = _time(now)
    last = _time(clock['last_accounted_at'])
    _need(now >= last, 'clock cannot move backward')
    if clock.get('waiting_since') is None:
        clock['consumed_s'] += now - last
    clock['last_accounted_at'] = now


def set_hil(clock, now, waiting):
    _need(type(waiting) is bool, 'waiting must be a bool')
    tick(clock, now)
    if waiting:
        _need(clock.get('waiting_since') is None, 'HIL wait already started')
        clock['waiting_since'] = now
    else:
        start = clock.get('waiting_since')
        _need(start is not None, 'HIL wait already stopped')
        clock['hil_wait_intervals'].append([start, now])
        clock['waiting_since'] = None


def remaining(clock, limit):
    limit = _number('limit', limit)
    return max(0, limit - clock['consumed_s'])


def retry_delay(policy, retry_index, random_value):
    _validate(policy)
    _need(type(retry_index) is int and retry_index >= 1, 'retry_index must be a positive integer')
    _need(not isinstance(random_value, bool) and isinstance(random_value, (int, float))
          and math.isfinite(random_value) and 0 <= random_value <= 1,
          'random_value must be finite and between 0 and 1')
    retry = policy['retry']
    ceiling = min(retry['cap_delay_s'], retry['base_delay_s'] * (2 ** (retry_index - 1)))
    return random_value * ceiling
