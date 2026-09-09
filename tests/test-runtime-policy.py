"""Run: python3 tests/test-runtime-policy.py."""
import importlib.util
from pathlib import Path
import unittest
import sys

sys.dont_write_bytecode = True


SCRIPT = Path(__file__).resolve().parents[1] / '.claude/skills/task-orchestrator/scripts/runtime_policy.py'


class RuntimePolicyChecks(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'runtime policy module must exist')
        spec = importlib.util.spec_from_file_location('runtime_policy', SCRIPT)
        self.policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.policy)

    def test_defaults_are_strict_and_safety_defaults_are_immutable(self):
        defaults = self.policy.DEFAULTS
        self.assertEqual(defaults['workflow_timeout_s'], 3600)
        self.assertEqual(defaults['stage_timeout_s'], 900)
        self.assertEqual(defaults['tool_timeout_s'], 120)
        self.assertEqual(defaults['approval_timeout_s'], 600)
        self.assertEqual(defaults['retry']['max_attempts'], 3)
        self.assertEqual(defaults['retry']['base_delay_s'], 1)
        self.assertEqual(defaults['retry']['cap_delay_s'], 30)
        self.assertEqual(defaults['retry']['max_elapsed_s'], 180)
        self.assertEqual(defaults['breaker']['failure_threshold'], 3)
        self.assertEqual(defaults['breaker']['cooldown_s'], 60)
        self.assertEqual(defaults['unknown_usage_policy'], 'awaiting_data')
        self.assertEqual(defaults['approval_default'], 'deny')

        with self.assertRaisesRegex(ValueError, 'unknown_usage_policy'):
            self.policy.merge_policy(defaults, {'unknown_usage_policy': 'allow'})
        with self.assertRaisesRegex(ValueError, 'approval_default'):
            self.policy.merge_policy(defaults, {'approval_default': 'approve'})

    def test_merge_policy_rejects_unknown_invalid_numeric_and_hierarchy(self):
        defaults = self.policy.DEFAULTS
        bad_patches = [
            {'extra': 1},
            {'retry': {'extra': 1}},
            {'stage_timeout_s': True},
            {'workflow_timeout_s': float('inf')},
            {'tool_timeout_s': 901},
            {'stage_timeout_s': 3601},
            {'retry': {'max_elapsed_s': 901}},
            {'retry': {'base_delay_s': 31}},
            {'retry': {'max_attempts': 0}},
            {'breaker': {'failure_threshold': 0}},
        ]
        for patch in bad_patches:
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    self.policy.merge_policy(defaults, patch)

    def test_merge_policy_allows_partial_nested_override_without_mutating_current(self):
        defaults = self.policy.DEFAULTS
        merged = self.policy.merge_policy(defaults, {'retry': {'cap_delay_s': 10}})
        self.assertEqual(merged['retry']['cap_delay_s'], 10)
        self.assertEqual(merged['retry']['base_delay_s'], 1)
        self.assertEqual(defaults['retry']['cap_delay_s'], 30)

    def test_clock_excludes_hil_wait_and_keeps_cumulative_time(self):
        sample = self.policy.new_clock(0)
        self.policy.set_hil(sample, 600, True)
        self.policy.set_hil(sample, 7800, False)
        self.assertEqual(self.policy.remaining(sample, 3600), 3000)

        clock = self.policy.new_clock(0)
        self.policy.tick(clock, 600)
        self.policy.set_hil(clock, 600, True)
        self.policy.tick(clock, 7800)
        self.policy.set_hil(clock, 7800, False)
        self.policy.tick(clock, 8400)

        self.assertEqual(clock['consumed_s'], 1200)
        self.assertEqual(clock['last_accounted_at'], 8400)
        self.assertEqual(clock['hil_wait_intervals'], [[600, 7800]])
        self.assertIsNone(clock['waiting_since'])
        self.assertEqual(self.policy.remaining(clock, 3600), 2400)

    def test_clock_rejects_backwards_or_nonfinite_time_and_bad_hil_transition(self):
        clock = self.policy.new_clock(10)
        with self.assertRaisesRegex(ValueError, 'backward'):
            self.policy.tick(clock, 9)
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.policy.tick(clock, float('nan'))
        with self.assertRaisesRegex(ValueError, 'already'):
            self.policy.set_hil(clock, 11, False)

    def test_retry_delay_uses_full_jitter_with_first_retry_index_one(self):
        policy = self.policy.merge_policy(self.policy.DEFAULTS, {'retry': {'base_delay_s': 2, 'cap_delay_s': 10}})
        self.assertEqual(self.policy.retry_delay(policy, 1, 0), 0)
        self.assertEqual(self.policy.retry_delay(policy, 1, 0.5), 1)
        self.assertEqual(self.policy.retry_delay(policy, 2, 0.5), 2)
        self.assertEqual(self.policy.retry_delay(policy, 4, 1), 10)
        with self.assertRaises(ValueError):
            self.policy.retry_delay(policy, 0, 0.5)
        with self.assertRaises(ValueError):
            self.policy.retry_delay(policy, 1, 1.01)


if __name__ == '__main__':
    unittest.main()
