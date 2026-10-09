"""Isolated Stage +2 safety and parity tests. No GitHub network/write."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import verify_bundle
from verify_bundle import StopVerification, verify

SOURCE = Path(__file__).resolve().parent / 'fixtures'


def call(*args):
    return subprocess.run(['git', *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()


class Stage2VerifierTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dksc-stage2-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'release'
        self.release.mkdir()
        self.manifest_path = self.release / 'publish-manifest.json'
        self.manifest = json.loads((SOURCE / 'publish-manifest.json').read_text())
        shutil.copyfile(SOURCE / self.manifest['bundle'], self.release / self.manifest['bundle'])
        self.write_manifest()
        self.remote = self.root / 'remote.git'
        call('init', '--bare', '--quiet', self.remote)
        call('--git-dir', self.remote, 'fetch', str(self.release / self.manifest['bundle']),
             'refs/heads/main:refs/heads/main')

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + '\n')

    def verify(self):
        return verify(self.release, test_remote_url=str(self.remote))

    def fail_at(self, check):
        with self.assertRaises(StopVerification) as e:
            self.verify()
        self.assertEqual(e.exception.check, check)

    def refs(self):
        return call('--git-dir', self.remote, 'show-ref')

    def tree_bytes(self, folder):
        return {str(path.relative_to(folder)): path.read_bytes()
                for path in folder.rglob('*') if path.is_file()}

    def make_bundle(self, contents='safe content\n', *, unrelated=False, filename='change.txt'):
        """小型fixtureから実Git履歴を作る。外部networkは使用しません。"""
        work = self.root / 'work'
        call('clone', '--quiet', self.release / self.manifest['bundle'], work)
        call('-C', work, 'config', 'user.name', 'Fixture')
        call('-C', work, 'config', 'user.email', 'fixture@example.invalid')
        if unrelated:
            call('-C', work, 'checkout', '--orphan', 'agent/unrelated')
            call('-C', work, 'rm', '-rf', '.')
            self.manifest['branch'] = 'agent/unrelated'
        else:
            call('-C', work, 'checkout', self.manifest['branch'])
        (work / filename).write_text(contents, encoding='utf-8')
        call('-C', work, 'add', filename)
        call('-C', work, 'commit', '--quiet', '-m', 'Fixture change')
        self.manifest['expectedHead'] = call('-C', work, 'rev-parse', 'HEAD')
        bundle = self.release / self.manifest['bundle']
        bundle.unlink()
        call('-C', work, 'bundle', 'create', bundle, self.manifest['branch'])
        self.manifest['bundleSha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        if not unrelated:
            main, head = self.manifest['expectedMain'], self.manifest['expectedHead']
            self.manifest['expectedFiles'] = call('-C', work, 'diff', '--name-only', '-z',
                                                    f'{main}...{head}').rstrip('\0').split('\0')
            self.manifest['expectedCommits'] = call('-C', work, 'rev-list', '--reverse',
                                                      f'{main}..{head}').splitlines()
        self.write_manifest()
        return work

    def test_valid_bundle_pass_and_no_remote_writes(self):
        before = self.refs()
        result = self.verify()
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['commitsFullyChecked'])
        self.assertTrue(result['fullyVerified'])
        self.assertEqual(result['verificationLevel'], 'full')
        self.assertEqual(result['remoteBranch'], 'missing')
        self.assertEqual(result['remoteWriteCount'], 0)
        self.assertEqual(before, self.refs())
        self.assertEqual(result['changedFiles'], self.manifest['expectedFiles'])

    def test_sha256_mismatch_stops_before_git(self):
        self.manifest['bundleSha256'] = '0' * 64
        self.write_manifest()
        before = self.refs()
        self.fail_at('bundle.sha256')
        self.assertEqual(before, self.refs())

    def test_corrupted_bundle_stops_before_git(self):
        (self.release / self.manifest['bundle']).write_bytes(b'not a valid git bundle')
        self.manifest['bundleSha256'] = hashlib.sha256(b'not a valid git bundle').hexdigest()
        self.write_manifest()
        self.fail_at('bundle.verify')

    def test_invalid_manifest_json_stops(self):
        self.manifest_path.write_text('{bad')
        self.fail_at('manifest.json')

    def test_bad_branch_ref_stops(self):
        self.manifest['branch'] = 'agent//invalid'
        self.write_manifest()
        self.fail_at('manifest.branch.gitRef')

    def test_wrong_base_head_stops(self):
        self.manifest['expectedMain'] = '1' * 40
        self.write_manifest()
        self.fail_at('base.head')

    def test_wrong_bundle_head_stops(self):
        self.manifest['expectedHead'] = '2' * 40
        self.write_manifest()
        self.fail_at('bundle.head')

    def test_mismatched_changed_files_stops(self):
        self.manifest['expectedFiles'] = ['README.md']
        self.write_manifest()
        self.fail_at('diff.files')

    def test_mismatched_commit_order_stops(self):
        self.manifest['expectedCommits'].reverse()
        self.write_manifest()
        self.fail_at('history.commits')

    def test_remote_same_head_is_idempotent_and_read_only(self):
        call('--git-dir', self.remote, 'fetch', str(self.release / self.manifest['bundle']),
             f'refs/heads/{self.manifest["branch"]}:refs/heads/{self.manifest["branch"]}')
        before = self.refs()
        result = self.verify()
        self.assertEqual(result['remoteBranch'], 'same')
        self.assertEqual(before, self.refs())

    def test_remote_different_head_stops_without_overwriting(self):
        call('--git-dir', self.remote, 'update-ref',
             f'refs/heads/{self.manifest["branch"]}', self.manifest['expectedMain'])
        before = self.refs()
        self.fail_at('remote.branch.head')
        self.assertEqual(before, self.refs())

    def test_empty_commits_warns_by_result_flag(self):
        self.manifest['expectedCommits'] = []
        self.write_manifest()
        result = self.verify()
        self.assertFalse(result['commitsFullyChecked'])
        self.assertFalse(result['fullyVerified'])
        self.assertEqual(result['verificationLevel'], 'partial')
        self.assertEqual(len(result['warnings']), 1)

    def test_direct_main_rejected(self):
        self.manifest['branch'] = 'main'
        self.write_manifest()
        self.fail_at('manifest.branch')

    def test_unrelated_history_stops_at_ancestor(self):
        self.make_bundle(unrelated=True)
        self.fail_at('history.ancestor')

    def test_whitespace_error_stops_without_source_disclosure(self):
        secret = 'PRIVATE_SOURCE_SENTINEL'
        self.make_bundle(secret + '  \n')
        with self.assertRaises(StopVerification) as error:
            self.verify()
        self.assertEqual(error.exception.check, 'diff.check')
        self.assertNotIn(secret, json.dumps(error.exception.as_dict()))

    def test_two_runs_do_not_change_remote_or_input(self):
        before_remote = self.tree_bytes(self.remote)
        before_release = self.tree_bytes(self.release)
        first, second = self.verify(), self.verify()
        self.assertEqual(first, second)
        self.assertEqual(before_remote, self.tree_bytes(self.remote))
        self.assertEqual(before_release, self.tree_bytes(self.release))

    def test_two_runs_after_same_head_also_read_only(self):
        call('--git-dir', self.remote, 'fetch', self.release / self.manifest['bundle'],
             f'refs/heads/{self.manifest["branch"]}:refs/heads/{self.manifest["branch"]}')
        before = self.tree_bytes(self.remote)
        self.assertEqual(self.verify(), self.verify())
        self.assertEqual(before, self.tree_bytes(self.remote))

    def test_commits_missing_element_stops(self):
        self.manifest['expectedCommits'].pop()
        self.write_manifest()
        self.fail_at('history.commits')

    def test_commits_wrong_sha_stops(self):
        self.manifest['expectedCommits'][0] = 'a' * 40
        self.write_manifest()
        self.fail_at('history.commits')

    def test_files_can_be_in_any_order(self):
        self.make_bundle()
        self.manifest['expectedFiles'].reverse()
        self.write_manifest()
        self.assertTrue(self.verify()['fullyVerified'])

    def test_unicode_and_space_filename_is_preserved(self):
        self.make_bundle(filename='日本語 space.txt')
        self.assertIn('日本語 space.txt', self.verify()['changedFiles'])

    def test_bundle_missing_stops(self):
        (self.release / self.manifest['bundle']).unlink()
        self.fail_at('bundle.exists')

    def test_bundle_symlink_outside_stops(self):
        bundle = self.release / self.manifest['bundle']
        target = self.root / 'external.bundle'
        bundle.rename(target)
        try:
            bundle.symlink_to(target)
        except OSError:
            self.skipTest('symlink unavailable')
        self.fail_at('bundle.location')

    def test_manifest_symlink_outside_stops(self):
        target = self.root / 'external.json'
        self.manifest_path.rename(target)
        try:
            self.manifest_path.symlink_to(target)
        except OSError:
            self.skipTest('symlink unavailable')
        self.fail_at('manifest.location')

    def test_size_limit_before_git(self):
        with patch.object(verify_bundle, 'MAX_BUNDLE_BYTES', 32), patch.object(verify_bundle, 'git') as git_mock:
            self.fail_at('bundle.size')
            git_mock.assert_not_called()

    def test_sha_mismatch_never_calls_git(self):
        self.manifest['bundleSha256'] = '0' * 64
        self.write_manifest()
        with patch.object(verify_bundle, 'git') as git_mock:
            self.fail_at('bundle.sha256')
            git_mock.assert_not_called()

    def test_pack_corruption_stops(self):
        bundle = self.release / self.manifest['bundle']
        data = bytearray(bundle.read_bytes())
        data[-25] ^= 0xff
        bundle.write_bytes(data)
        self.manifest['bundleSha256'] = hashlib.sha256(data).hexdigest()
        self.write_manifest()
        self.fail_at('bundle.fetch')

    def test_incremental_bundle_is_not_self_contained(self):
        work = self.make_bundle()
        bundle = self.release / self.manifest['bundle']
        bundle.unlink()
        call('-C', work, 'bundle', 'create', bundle,
             f'{self.manifest["expectedMain"]}..{self.manifest["branch"]}')
        self.manifest['bundleSha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        self.write_manifest()
        self.fail_at('bundle.verify')

    def test_missing_bundle_branch_stops(self):
        self.manifest['branch'] = 'agent/not-in-bundle'
        self.write_manifest()
        self.fail_at('bundle.fetch')

    def test_invalid_base_branch_stops(self):
        self.manifest['baseBranch'] = 'bad..ref'
        self.write_manifest()
        self.fail_at('manifest.baseBranch.gitRef')

    def test_git_environment_cannot_redirect_repository(self):
        before = self.tree_bytes(self.remote)
        with patch.dict(os.environ, {'GIT_DIR': str(self.remote), 'GIT_WORK_TREE': str(self.release),
                                    'GIT_TEMPLATE_DIR': str(self.root),
                                    'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'url.bad.insteadOf',
                                    'GIT_CONFIG_VALUE_0': 'https://github.com/'}):
            self.assertTrue(self.verify()['fullyVerified'])
        self.assertEqual(before, self.tree_bytes(self.remote))

    def test_temp_repository_removed_on_pass_and_stop(self):
        real_temp = tempfile.TemporaryDirectory
        paths = []

        def tracked_temp(*args, **kwargs):
            temporary = real_temp(*args, **kwargs)
            paths.append(Path(temporary.name))
            return temporary

        with patch.object(verify_bundle.tempfile, 'TemporaryDirectory', side_effect=tracked_temp):
            self.verify()
            self.manifest['expectedHead'] = '2' * 40
            self.write_manifest()
            self.fail_at('bundle.head')
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_git_timeout_is_stop_without_command_content(self):
        with patch.object(verify_bundle.subprocess, 'run',
                          side_effect=subprocess.TimeoutExpired('PRIVATE_COMMAND_SENTINEL', 120)):
            with self.assertRaises(StopVerification) as error:
                self.verify()
        self.assertEqual(error.exception.check, 'git.execution')
        self.assertNotIn('PRIVATE_COMMAND_SENTINEL', json.dumps(error.exception.as_dict()))

    def test_cli_io_failure_returns_json_stop(self):
        with patch.object(verify_bundle, 'verify', side_effect=PermissionError()), \
             patch('builtins.print') as output:
            self.assertEqual(verify_bundle.main(['verify_bundle.py', str(self.release)]), 1)
        self.assertEqual(json.loads(output.call_args.args[0])['check'], 'input.io')

    def test_only_read_operations_are_issued_without_checkout(self):
        original = verify_bundle.git
        operations = []

        def tracked_git(args, **kwargs):
            operations.append(args[2] if args[0] == '-C' else args[0])
            return original(args, **kwargs)

        with patch.object(verify_bundle, 'git', side_effect=tracked_git):
            self.verify()
        self.assertLessEqual(set(operations), {'check-ref-format', 'init', 'bundle', 'remote',
                                             'config', 'fetch', 'rev-parse', 'fsck', 'merge-base',
                                             'diff', 'rev-list', 'ls-remote'})
        self.assertFalse(set(operations) & {'push', 'checkout', 'tag', 'merge', 'reset', 'rebase'})

    def test_bundle_snapshot_is_used_even_if_input_changes(self):
        original = verify_bundle.git
        first = True

        def change_source_then_git(args, **kwargs):
            nonlocal first
            if first:
                first = False
                (self.release / self.manifest['bundle']).write_bytes(b'changed after hashing')
            return original(args, **kwargs)

        with patch.object(verify_bundle, 'git', side_effect=change_source_then_git):
            self.assertTrue(self.verify()['fullyVerified'])


if __name__ == '__main__':
    unittest.main()
