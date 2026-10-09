"""Mock startup regression tests for the installed external helper.

Run with Python -B -X utf8 tools/test_coordinator_startup.py --helper <path>.
The helper is not deployed by this repository; an explicit missing path fails.
Discovery without a selected helper skips this suite. No RPC, terminal, process
launch, test file, database or bytecode is created by the tests.
"""

import argparse
import json
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch


HELPER = None


class StartupHarness:
    def __init__(self, helper):
        self.helper = helper
        self.worktree = Path('C:/mock/task').resolve()
        self.branch = 'task/29-startup'
        self.head = 'a' * 40
        self.created = False
        self.calls = []
        self.rpc_calls = []
        self.create_error = None
        self.create_receipt = {'terminal': {'handle': 'new-terminal', 'surface': 'visible'}}
        self.before_terminals = [self.terminal('existing-shell')]
        self.after_terminals = [*self.before_terminals, self.terminal('new-terminal')]
        self.inventory_error = None
        self.baseline_incomplete = False
        self.reconcile_rpc_error = None
        self.dispatch_error = None
        self.thread = {'id': 'new-thread', 'sessionId': 'runtime-session',
                       'cwd': str(self.worktree), 'model': 'gpt-6.1-sol',
                       'reasoningEffort': 'ultra', 'status': {'type': 'idle'}}
        self.history = [self.thread]

    def terminal(self, handle, path=None):
        return {'handle': handle, 'worktreePath': str(path or self.worktree),
                'branch': f'refs/heads/{self.branch}', 'connected': True,
                'writable': True, 'orphaned': False, 'preview': 'GPT-6.1-Sol ultra'}

    def orca(self, *args):
        self.calls.append(args)
        if args[:2] == ('worktree', 'show'):
            return {'worktree': {'path': str(self.worktree), 'head': self.head,
                                 'branch': f'refs/heads/{self.branch}'}}
        if args[:2] == ('terminal', 'list'):
            if self.created and self.inventory_error:
                raise self.inventory_error
            return {'terminals': self.after_terminals if self.created else self.before_terminals,
                    'truncated': self.baseline_incomplete and not self.created,
                    'hostScope': {'omittedHostIds': []}}
        if args[:2] == ('terminal', 'create'):
            self.created = True
            if self.create_error:
                raise self.create_error
            return self.create_receipt
        if args[:2] == ('terminal', 'show'):
            return {'terminal': self.terminal('new-terminal')}
        if args[:2] == ('terminal', 'read'):
            return {'terminal': {'tail': []}}
        raise AssertionError(f'Unexpected Orca mutation/call: {args}')

    def request(self, method, params):
        self.rpc_calls.append((method, params))
        if self.created and self.reconcile_rpc_error and method == 'thread/list':
            raise self.reconcile_rpc_error
        if method == 'thread/list':
            return {'data': self.history if self.created else []}
        if method == 'thread/loaded/list':
            return {'data': [self.thread['id']] if self.created else []}
        if method == 'thread/read':
            return {'thread': self.thread}
        if method == 'turn/start':
            if self.dispatch_error:
                raise self.dispatch_error
            return {'turn': {'id': 'first-turn', 'status': 'inProgress'}}
        raise AssertionError(f'Unexpected RPC call: {method}')

    def run(self):
        with patch.object(self.helper, 'orca', self.orca), \
                patch.object(self.helper.Path, 'is_file', return_value=True), \
                patch.object(self.helper, 'validate_worktree', return_value=self.worktree), \
                patch.object(self.helper.time, 'monotonic', return_value=0), \
                patch.object(self.helper.time, 'sleep', side_effect=AssertionError('Unexpected readiness wait')):
            return self.helper.start_visible_coordinator(
                self, Path('C:/mock/repo'), self.worktree, self.branch, self.head, 'Mock task')

    def failed_receipt(self, testcase):
        with testcase.assertRaises(RuntimeError) as failure:
            self.run()
        return json.loads(str(failure.exception))

    def create_count(self):
        return sum(call[:2] == ('terminal', 'create') for call in self.calls)

    def dispatch_count(self):
        return sum(method == 'turn/start' for method, _ in self.rpc_calls)


class CoordinatorStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HELPER is None:
            raise unittest.SkipTest('External helper not selected; run this file with --helper <path>')

    def setUp(self):
        self.harness = StartupHarness(HELPER)

    def assert_withheld(self, receipt):
        self.assertEqual(receipt['startup'], 'unverified')
        self.assertEqual(receipt['taskSubmission'], 'not sent')
        self.assertEqual(self.harness.dispatch_count(), 0)
        self.assertEqual(self.harness.create_count(), 1)
        self.assertIn('do not create again', receipt['nextAction'])

    def test_success_preserves_verified_runtime_and_single_dispatch(self):
        result = self.harness.run()
        self.assertEqual(result['startup'], 'verified')
        self.assertEqual(result['terminalHandle'], 'new-terminal')
        self.assertEqual(result['threadId'], 'new-thread')
        self.assertEqual(result['reasoningEffort'], 'ultra')
        self.assertEqual(result['startingHead'], self.harness.head)
        self.assertEqual(self.harness.create_count(), 1)
        self.assertEqual(self.harness.dispatch_count(), 1)
        turn_params = next(params for method, params in self.harness.rpc_calls if method == 'turn/start')
        self.assertEqual(turn_params['input'], [{'type': 'text', 'text': 'Mock task'}])

    def test_timeout_after_creation_reports_candidates_without_claiming_owner(self):
        self.harness.create_error = subprocess.TimeoutExpired(['orca', 'terminal', 'create'], 30)
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertIsNone(receipt['terminalHandle'])
        self.assertEqual(receipt['reconciliation']['terminalCandidates'], [
            {'handle': 'existing-shell', 'observedBeforeCreate': True},
            {'handle': 'new-terminal', 'observedBeforeCreate': False}])
        self.assertEqual(receipt['reconciliation']['sessionCandidates'], [
            {'threadId': 'new-thread', 'loadedBeforeCreate': False}])
        self.assertIn('without assuming ownership', receipt['residual'])

    def test_non_json_error_from_creation_is_guarded(self):
        self.harness.create_error = RuntimeError('Orca returned no JSON receipt (exit 0)')
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertIn('no JSON receipt', receipt['reason'])
        self.assertIsNone(receipt['terminalHandle'])

    def test_error_receipt_from_creation_is_guarded(self):
        self.harness.create_error = RuntimeError('{"code":"transport_closed"}')
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertIn('transport_closed', receipt['reason'])

    def test_missing_handle_in_creation_receipt_is_guarded(self):
        self.harness.create_receipt = {'terminal': {'surface': 'visible'}}
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertIsNone(receipt['terminalHandle'])
        self.assertIn('no valid handle', receipt['reason'])

    def test_missing_terminal_in_creation_receipt_is_guarded(self):
        self.harness.create_receipt = {}
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertEqual(receipt['reconciliation']['terminalInventory'], 'complete')

    def test_failed_reconciliation_preserves_original_error_and_unknowns(self):
        self.harness.create_error = RuntimeError('Create acknowledgement lost')
        self.harness.inventory_error = RuntimeError('Terminal list unavailable')
        self.harness.reconcile_rpc_error = RuntimeError('Session list unavailable')
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertEqual(receipt['reason'], 'Create acknowledgement lost')
        self.assertEqual(receipt['reconciliation']['terminalInventory'], 'unverified')
        self.assertEqual(receipt['reconciliation']['sessionInventory'], 'unverified')
        self.assertIn('Terminal list unavailable', receipt['reconciliation']['errors']['terminals'])
        self.assertIn('Session list unavailable', receipt['reconciliation']['errors']['sessions'])

    def test_multiple_new_terminals_remain_candidates_without_auto_selection(self):
        self.harness.create_error = RuntimeError('Create acknowledgement lost')
        self.harness.after_terminals.append(self.harness.terminal('concurrent-terminal'))
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertIsNone(receipt['terminalHandle'])
        self.assertEqual(len(receipt['reconciliation']['terminalCandidates']), 3)

    def test_exact_worktree_filter_excludes_other_workspace_and_child_session(self):
        self.harness.create_error = RuntimeError('Create acknowledgement lost')
        self.harness.after_terminals.append(self.harness.terminal('foreign-terminal', Path('C:/mock/other')))
        self.harness.history.extend([
            {**self.harness.thread, 'id': 'foreign-thread', 'cwd': str(Path('C:/mock/other').resolve())},
            {**self.harness.thread, 'id': 'child-thread', 'parentThreadId': 'new-thread'}])
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertEqual(len(receipt['reconciliation']['terminalCandidates']), 2)
        self.assertEqual(receipt['reconciliation']['sessionCandidates'], [
            {'threadId': 'new-thread', 'loadedBeforeCreate': False}])

    def test_known_handle_later_gate_failure_is_reported_and_not_dispatched(self):
        self.harness.create_receipt['terminal']['surface'] = 'background'
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertEqual(receipt['terminalHandle'], 'new-terminal')
        self.assertIn('visible UI', receipt['reason'])

    def test_pre_existing_handle_returned_by_create_is_not_dispatched(self):
        self.harness.create_receipt['terminal']['handle'] = 'existing-shell'
        receipt = self.harness.failed_receipt(self)
        self.assert_withheld(receipt)
        self.assertIn('pre-existing terminal', receipt['reason'])

    def test_dispatch_acknowledgement_loss_is_unproven_and_never_resent(self):
        self.harness.dispatch_error = RuntimeError('Turn acknowledgement lost')
        receipt = self.harness.failed_receipt(self)
        self.assertEqual(receipt['taskSubmission'], 'unproven; inspect before retrying')
        self.assertEqual(receipt['terminalHandle'], 'new-terminal')
        self.assertEqual(receipt['threadId'], 'new-thread')
        self.assertEqual(self.harness.dispatch_count(), 1)
        self.assertEqual(self.harness.create_count(), 1)

    def test_incomplete_baseline_inventory_prevents_creation(self):
        self.harness.baseline_incomplete = True
        receipt = self.harness.failed_receipt(self)
        self.assertFalse(receipt['createAttempted'])
        self.assertEqual(receipt['taskSubmission'], 'not sent')
        self.assertEqual(self.harness.create_count(), 0)
        self.assertEqual(self.harness.dispatch_count(), 0)
        self.assertIn('inventory is incomplete', receipt['reason'])


def main():
    global HELPER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', required=True, type=Path, help='Installed external codex-session-control.py')
    args, unittest_args = parser.parse_known_args()
    if not args.helper.is_file():
        parser.error(f'Explicit helper path does not exist: {args.helper}')
    HELPER = types.ModuleType('external_codex_session_control')
    HELPER.__file__ = str(args.helper.resolve())
    exec(compile(args.helper.read_text(encoding='utf-8'), str(args.helper), 'exec'), HELPER.__dict__)
    unittest.main(argv=[__file__, *unittest_args])


if __name__ == '__main__':
    main()
