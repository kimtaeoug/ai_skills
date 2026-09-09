"""Run: python3 tests/test-task-orchestrator.py (stdlib, isolated Git workspaces)."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys

sys.dont_write_bytecode = True


SCRIPT = Path(__file__).resolve().parents[1] / '.claude/skills/task-orchestrator/scripts/task_state.py'


class GraphChecks(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'task state engine must exist')
        spec = importlib.util.spec_from_file_location('task_state', SCRIPT)
        self.engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.engine)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.workspace)], check=True)
        (self.workspace / 'app.txt').write_text('initial\n')
        self.task = self.engine.initialize(self.workspace, 'Example task')

    def state(self):
        return json.loads((self.task / 'state.json').read_text())

    def event(self, event_type, **values):
        return self.engine.apply(self.task, self.state()['revision'], {'type': event_type, **values})

    def evidence(self, name='result.txt', text='Executed check: PASS'):
        path = self.task / 'artifacts' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return str(path)

    def approve(self, gate, **extra):
        return self.event('approve', gate=gate, user={'reference': 'conversation:turn-7', 'message': 'Approved'}, **extra)

    def prepare(self, ui=False, items=None):
        checks = ['TEST-01', 'TEST-02'] if ui else ['TEST-01']
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'Works as agreed', 'checks': checks}],
                   ui_required=ui, ui_reason='UI impact reviewed',
                   budget={'max_attempts': 10, 'max_no_progress': 2})
        self.approve('criteria')
        self.event('plan', items=items or [self.item('DEV-01')])
        self.approve('plan')

    def item(self, ident, depends=None, files=None):
        return {'id': ident, 'description': 'Change and regression check',
                'depends_on': depends or [], 'owns_files': files or ['app.txt'], 'resources': [],
                'criteria_ids': ['AC-01'], 'risk': 'low', 'complexity': 'small'}

    def start(self, ident='DEV-01'):
        return self.event('start', id=ident, model={'tier': 'cheap', 'actual': 'test-model', 'reason': 'Available low-cost model'})

    def finish(self, ident='DEV-01'):
        return self.event('finish', id=ident, attempt=self.state()['items'][ident]['attempt'],
                          status='done', evidence=self.evidence(ident + '.txt'))

    def check(self, ident='TEST-01', kind='code', status='pass', fingerprint=None):
        return self.event('check', id=ident, kind=kind, status=status, command='test command',
                          fingerprint=fingerprint or self.engine.snapshot(self.workspace),
                          evidence=self.evidence(ident + '.txt', status))

    def test_completion_requires_ui_current_approval_and_report(self):
        self.prepare(ui=True)
        self.start()
        self.finish()
        self.check()
        self.event('evaluate')
        self.assertEqual(self.state()['phase'], 'reassess_hil')
        self.approve('reassess', route='testing')
        self.check('TEST-02', 'ui')
        self.event('evaluate')
        self.assertEqual(self.state()['phase'], 'final_hil')
        with self.assertRaises(ValueError):
            self.event('complete', summary='Premature')
        self.approve('final')
        self.event('complete', summary='Implemented and verified', limitations=['None observed'])
        self.assertEqual(self.state()['phase'], 'completed')
        report = (self.task / 'report.md').read_text()
        self.assertIn('AC-01', report)
        self.assertIn('TEST-02', report)
        self.assertIn('test-model', report)

    def test_code_change_invalidates_final_approval(self):
        self.prepare()
        self.start()
        self.finish()
        self.check()
        self.event('evaluate')
        self.approve('final')
        (self.workspace / 'app.txt').write_text('changed after approval')
        with self.assertRaisesRegex(ValueError, 'stale|changed'):
            self.event('complete', summary='Must not complete')
        self.assertFalse((self.task / 'report.md').exists())

    def test_criteria_revision_requires_new_agreement(self):
        self.prepare()
        self.start()
        self.finish()
        self.check()
        self.event('evaluate')
        self.approve('final')
        self.event('pause', reason='Expected behavior changed')
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'New behavior', 'checks': ['TEST-01']}],
                   ui_required=False, ui_reason='CLI only', budget={'max_attempts': 10, 'max_no_progress': 2})
        self.assertEqual(self.state()['criteria_version'], 2)
        with self.assertRaises(ValueError):
            self.start()
        with self.assertRaises(ValueError):
            self.approve('final')
        self.assertEqual(self.state()['checks'], {})

    def test_dependencies_conflicts_and_attempt_identity(self):
        self.prepare(items=[self.item('DEV-01'), self.item('DEV-02', ['DEV-01'])])
        with self.assertRaises(ValueError):
            self.start('DEV-02')
        self.start()
        self.finish()
        self.start('DEV-02')
        self.finish('DEV-02')
        self.check(status='fail')
        self.event('evaluate')
        self.event('rework', ids=['DEV-01'], reason='Shared contract failure')
        self.assertEqual(self.state()['items']['DEV-02']['status'], 'pending')
        self.start()
        self.assertEqual(self.state()['items']['DEV-01']['attempt'], 2)

    def test_parallel_writers_cannot_own_overlapping_paths(self):
        self.prepare(items=[self.item('DEV-01', files=['src']), self.item('DEV-02', files=['src/app.py'])])
        self.start()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.start('DEV-02')

    def test_invalid_cycle_and_unapproved_model_escalation(self):
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'Goal', 'checks': ['TEST-01']}],
                   ui_required=False, ui_reason='CLI', budget={'max_attempts': 10, 'max_no_progress': 2})
        self.approve('criteria')
        with self.assertRaisesRegex(ValueError, 'cycle'):
            self.event('plan', items=[self.item('DEV-01', ['DEV-02']), self.item('DEV-02', ['DEV-01'])])
        self.event('plan', items=[self.item('DEV-01')])
        self.approve('plan')
        with self.assertRaises(ValueError):
            self.event('start', id='DEV-01', model={'tier': 'high', 'actual': 'expensive', 'reason': ''})

    def test_revision_lock_local_ids_and_path_escape(self):
        second = self.engine.initialize(self.workspace, 'Same title')
        self.assertNotEqual(second, self.task)
        old = self.state()['revision']
        self.event('pause', reason='User pause')
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.engine.apply(self.task, old, {'type': 'pause', 'reason': 'Stale writer'})
        with self.assertRaises(ValueError):
            self.engine.apply(self.workspace, 0, {'type': 'pause', 'reason': 'Wrong root'})

    def test_evidence_and_fingerprint_cannot_be_reused(self):
        self.prepare()
        self.start()
        self.finish()
        before = self.engine.snapshot(self.workspace)
        (self.workspace / 'app.txt').write_text('new code')
        with self.assertRaises(ValueError):
            self.check(fingerprint=before)
        self.check()
        self.evidence('TEST-01.txt', 'overwritten evidence')
        self.event('evaluate')
        self.assertNotEqual(self.state()['phase'], 'final_hil')

    def test_required_research_failure_blocks_planning(self):
        self.event('research', id='RES-01', question='Which API exists?', required=True,
                   status='no-confirmed-claims', evidence=self.evidence('research.txt', 'No verified claims'))
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'Goal', 'checks': ['TEST-01']}],
                   ui_required=False, ui_reason='CLI', budget={'max_attempts': 10, 'max_no_progress': 2})
        self.approve('criteria')
        with self.assertRaisesRegex(ValueError, 'research'):
            self.event('plan', items=[self.item('DEV-01')])

    def test_ui_cannot_precede_code_verification(self):
        self.prepare(ui=True)
        self.start()
        self.finish()
        with self.assertRaisesRegex(ValueError, 'code'):
            self.check('TEST-02', 'ui')

    def test_stall_returns_to_hil_without_declaring_success(self):
        self.prepare()
        for attempt in range(3):
            self.start()
            self.finish()
            self.check(status='fail')
            self.event('evaluate')
            if attempt < 2:
                self.event('rework', ids=['DEV-01'], reason='Try a different fix')
        self.assertEqual(self.state()['phase'], 'reassess_hil')
        with self.assertRaises(ValueError):
            self.start()

    def test_issue_resolution_requires_a_fresh_passing_test(self):
        self.prepare()
        self.start()
        self.finish()
        record = {'id': 'ISSUE-01', 'task_id': 'DEV-01', 'description': 'Broken behavior',
                  'evidence': self.evidence('issue.txt')}
        self.event('issue', status='open', **record)
        with self.assertRaises(ValueError):
            self.event('issue', status='resolved', check_id='TEST-01', **record)
        self.check()
        self.event('evaluate')
        self.assertEqual(self.state()['phase'], 'triage')
        self.event('issue', status='resolved', check_id='TEST-01', **record)
        self.event('evaluate')
        self.assertEqual(self.state()['phase'], 'final_hil')

    def test_other_task_in_same_workspace_cannot_claim_running_files(self):
        self.prepare()
        self.start()
        self.task = self.engine.initialize(self.workspace, 'Second task')
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.start()

    def test_glob_ownership_cannot_bypass_overlap_checks(self):
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'Goal', 'checks': ['TEST-01']}],
                   ui_required=False, ui_reason='CLI', budget={'max_attempts': 10, 'max_no_progress': 2})
        self.approve('criteria')
        with self.assertRaisesRegex(ValueError, 'literal'):
            self.event('plan', items=[self.item('DEV-01', files=['src/*.py'])])

    def test_report_write_failure_cannot_commit_completion(self):
        self.prepare()
        self.start()
        self.finish()
        self.check()
        self.event('evaluate')
        self.approve('final')
        (self.task / 'report.md').mkdir()
        revision = self.state()['revision']
        with self.assertRaises(OSError):
            self.event('complete', summary='Cannot save report')
        self.assertEqual(self.state()['revision'], revision)
        self.assertEqual(self.state()['phase'], 'reporting')

    def test_approval_requires_a_human_message_reference(self):
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'Goal', 'checks': ['TEST-01']}],
                   ui_required=False, ui_reason='CLI', budget={'max_attempts': 10, 'max_no_progress': 2})
        with self.assertRaisesRegex(ValueError, 'user message'):
            self.event('approve', gate='criteria', user={'reference': '', 'message': 'Presumed approval'})

    def test_revised_criteria_require_reassessed_research(self):
        self.prepare()
        self.event('pause', reason='Need different upstream behavior')
        self.approve('reassess', route='planning')
        self.event('research', id='RES-01', question='Old API behavior', required=True,
                   status='answered', evidence=self.evidence('research.txt', 'Old API documented'))
        self.event('criteria', items=[{'id': 'AC-01', 'text': 'New API behavior', 'checks': ['TEST-01']}],
                   ui_required=False, ui_reason='CLI', budget={'max_attempts': 10, 'max_no_progress': 2})
        self.approve('criteria')
        with self.assertRaisesRegex(ValueError, 'research'):
            self.event('plan', items=[self.item('DEV-01')])

    def test_replanning_requires_explicit_issue_reassignment(self):
        self.prepare()
        original = {'id': 'ISSUE-01', 'task_id': 'DEV-01', 'description': 'Original defect',
                    'evidence': self.evidence('issue.txt')}
        self.event('issue', status='open', **original)
        with self.assertRaisesRegex(ValueError, 'issue-reassign'):
            self.event('issue', status='open', fixing_task_id='FIX-01', **original)
        self.event('pause', reason='Replan owner')
        self.approve('reassess', route='planning')
        with self.assertRaisesRegex(ValueError, 'issue'):
            self.event('plan', items=[self.item('FIX-01')])
        self.event('issue-reassign', id='ISSUE-01', fixing_task_id='FIX-01', reason='Move repair to dedicated work item')
        self.event('plan', items=[self.item('FIX-01')])
        self.approve('plan')
        self.start('FIX-01')
        self.finish('FIX-01')
        self.check()
        with self.assertRaises(ValueError):
            self.event('issue', id='ISSUE-01', task_id='FIX-01', description='Rewritten identity',
                       status='resolved', check_id='TEST-01', evidence=original['evidence'])
        self.event('issue', status='resolved', check_id='TEST-01', **original)
        self.assertEqual(self.state()['issues']['ISSUE-01']['task_id'], 'DEV-01')
        self.assertEqual(self.state()['issues']['ISSUE-01']['fixing_task_id'], 'FIX-01')

    def test_resume_evaluation_preserves_current_final_approval(self):
        self.prepare()
        self.start()
        self.finish()
        self.check()
        self.event('evaluate')
        self.approve('final')
        approval = self.state()['approvals']['final']
        self.event('evaluate')
        self.assertEqual(self.state()['phase'], 'reporting')
        self.assertEqual(self.state()['approvals']['final'], approval)
        self.event('complete', summary='Resumed without redundant approval')

    def test_reintroduced_work_id_keeps_attempt_history(self):
        self.prepare()
        self.start()
        self.finish()
        for ident in ('FIX-01', 'DEV-01'):
            self.event('pause', reason='Replan work')
            self.approve('reassess', route='planning')
            self.event('plan', items=[self.item(ident)])
            self.approve('plan')
        self.start()
        self.assertEqual(self.state()['items']['DEV-01']['attempt'], 2)


if __name__ == '__main__':
    unittest.main()
