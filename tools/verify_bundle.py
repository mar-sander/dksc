#!/usr/bin/env python3
"""DKSC Stage +2: read-only Git bundle verifier.

Run with ``python tools/verify_bundle.py /path/to/release-folder``.
The folder must contain publish-manifest.json and the named .bundle.
This command is READ ONLY with respect to remote repositories: no push, PR or merge.

The normal CLI always derives the remote from manifest.repository as HTTPS GitHub.
Tests inject a *local* bare repository through verify(..., test_remote_url=...).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 120
FIELDS = (
    'release', 'repository', 'baseBranch', 'expectedMain', 'branch',
    'expectedHead', 'bundle', 'bundleSha256',
)
ARRAYS = ('expectedFiles', 'expectedCommits')
SHA40 = re.compile(r'[0-9a-fA-F]{40}\Z')
SHA64 = re.compile(r'[0-9a-fA-F]{64}\Z')
REPOSITORY = re.compile(
    r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/'
    r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98})\Z'
)
RESERVED = re.compile(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|\Z)', re.I)


class StopVerification(Exception):
    """Machine-readable fail-closed STOP with a stable check name."""

    def __init__(self, check: str, message: str, expected: str = '', actual: str = ''):
        super().__init__(message)
        self.check = check
        self.expected = str(expected)
        self.actual = str(actual)

    def as_dict(self) -> dict[str, str]:
        return {
            'status': 'STOP', 'check': self.check,
            'message': str(self), 'expected': self.expected, 'actual': self.actual,
        }


def stop(check: str, message: str, expected: str = '', actual: str = '') -> None:
    raise StopVerification(check, message, expected, actual)


def valid_filename(filename: str) -> bool:
    if not filename or len(filename) > 240 or filename in ('.', '..'):
        return False
    if not filename.lower().endswith('.bundle') or re.search(r'[\\/:*?"<>|\x00-\x1f]', filename):
        return False
    if filename.endswith(('.', ' ')) or RESERVED.match(filename):
        return False
    return True


def load_manifest(folder: Path) -> dict[str, Any]:
    path = folder / 'publish-manifest.json'
    if path.is_symlink():
        stop('manifest.location', 'manifestのsymbolic linkは受理しません')
    if not path.is_file():
        stop('manifest.exists', 'publish-manifest.json がありません')
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        stop('manifest.size', 'manifest は 1 MiB 以下にしてください')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        stop('manifest.json', 'manifest のJSON解析に失敗しました', actual=str(exc))
    if not isinstance(data, dict):
        stop('manifest.root', 'manifest のrootはobjectである必要があります')

    for key in FIELDS:
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            stop('manifest.' + key, '必須の空でない文字列がありません')
        data[key] = data[key].strip()
    for key in ARRAYS:
        if key not in data or not isinstance(data[key], list):
            stop('manifest.' + key, '必須のJSON配列がありません')

    if len(data['release']) > 100 or re.search(r'[\x00-\x1f]', data['release']):
        stop('manifest.release', 'releaseの形式が不正です')
    if not REPOSITORY.fullmatch(data['repository']) or data['repository'].lower().endswith('.git'):
        stop('manifest.repository', 'owner/repository形式ではありません')
    for key in ('branch', 'baseBranch'):
        value = data[key]
        if len(value) > 240 or not re.match(r'[A-Za-z0-9]', value):
            stop('manifest.' + key, 'branch形式が不正です')
    if data['branch'].lower() in ('main', data['baseBranch'].lower()):
        stop('manifest.branch', 'mainまたはbaseBranchへの直接pushは禁止です')
    for key in ('expectedMain', 'expectedHead'):
        if not SHA40.fullmatch(data[key]):
            stop('manifest.' + key, '40桁のhex SHAが必要です')
        data[key] = data[key].lower()
    if not SHA64.fullmatch(data['bundleSha256']):
        stop('manifest.bundleSha256', '64桁のhex SHA256が必要です')
    data['bundleSha256'] = data['bundleSha256'].upper()
    if not valid_filename(data['bundle']):
        stop('manifest.bundle', '安全な.bundleファイル名が必要です')

    files = []
    for item in data['expectedFiles']:
        if not isinstance(item, str) or not item.strip():
            stop('manifest.expectedFiles', '相対pathとして空でない文字列が必要です')
        item = item.strip()
        if item.startswith('/') or '\\' in item or re.search(r'(^|/)\.\.(/|$)|[\x00-\x1f]', item):
            stop('manifest.expectedFiles', '安全でないpathです', actual=item)
        if item in files:
            stop('manifest.expectedFiles', '重複したpathがあります', actual=item)
        files.append(item)
    data['expectedFiles'] = files
    commits = []
    for item in data['expectedCommits']:
        if not isinstance(item, str) or not SHA40.fullmatch(item):
            stop('manifest.expectedCommits', '40桁SHA以外の要素があります')
        item = item.lower()
        if item in commits:
            stop('manifest.expectedCommits', '重複したcommitがあります', actual=item)
        commits.append(item)
    data['expectedCommits'] = commits
    return data


def sha256_file(path: Path, *, snapshot: Path | None = None) -> str:
    """照合した同じbytesをGitに渡す。途中の差し替え・増大も検出します。"""
    digest = hashlib.sha256()
    total = 0
    with path.open('rb') as handle, (snapshot or Path(os.devnull)).open('wb') as output:
        while chunk := handle.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_BUNDLE_BYTES:
                stop('bundle.size', 'Stage +2Aの処理上限を超えています。bundle不正ではありません',
                     MAX_BUNDLE_BYTES, total)
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest().upper()


def git(args: list[str], *, cwd: Path | None = None, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    # Never inherit user-level URL rewrites or credential helpers.  No prompts.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '', 'GIT_OPTIONAL_LOCKS': '0',
                'GIT_NO_REPLACE_OBJECTS': '1'})
    try:
        result = subprocess.run(
            ['git', '--no-pager', '-c', f'core.hooksPath={os.devnull}',
             '-c', 'credential.helper=', '-c', 'protocol.allow=never',
             '-c', 'protocol.https.allow=always', '-c', 'protocol.file.allow=always',
             *args], cwd=cwd, env=env, text=True, encoding='utf-8',
            errors='strict', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except UnicodeError:
        stop('git.output', 'Git出力をUTF-8として解釈できません。置換して照合はしません')
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Gitのstderr・diff出力にはソース本文やURL等が入り得るため返しません。
        stop('git.execution', 'Gitコマンドの実行に失敗しました', actual=type(exc).__name__)
    if result.returncode and not allow_failure:
        stop('git.' + args[0], 'Gitが失敗しました', 'exit code 0',
             f'exit {result.returncode}')
    return result


def git_checked(check: str, args: list[str], *, cwd: Path | None = None) -> str:
    result = git(args, cwd=cwd, allow_failure=True)
    if result.returncode:
        stop(check, 'Git検証でSTOPしました', 'exit 0',
             f'exit {result.returncode}')
    return result.stdout


def single_ref(check: str, output: str) -> str:
    output = output.strip()
    if not SHA40.fullmatch(output):
        stop(check, 'Git refのSHAを一意に取得できません', '40桁SHA', output)
    return output.lower()


def remote_branch_state(repo: Path, branch: str, expected_head: str) -> str:
    ref = f'refs/heads/{branch}'
    result = git_checked('remote.branch', ['-C', str(repo), 'ls-remote', '--heads', 'origin', ref]).strip()
    if result == '':
        return 'missing'
    lines = result.splitlines()
    match = re.fullmatch(r'([0-9a-fA-F]{40})\s+' + re.escape(ref), result)
    if len(lines) != 1 or not match:
        stop('remote.branch.output', 'remote同名branchの出力形式が不正です', actual=result)
    actual = match.group(1).lower()
    if actual != expected_head:
        stop('remote.branch.head', 'remote同名branchは別HEADです。上書きしません', expected_head, actual)
    return 'same'


def verify(folder: Path, *, test_remote_url: str | None = None) -> dict[str, Any]:
    """Read-only verification. test_remote_url is ONLY for offline isolated tests.

    The CLI below exposes no flag to set a remote URL; production always HTTPS GitHub.
    """
    folder = folder.resolve()
    if not folder.is_dir():
        stop('input.folder', 'release folderが見つかりません')
    if not shutil.which('git'):
        stop('git.exists', 'Gitが見つかりません')

    manifest = load_manifest(folder)
    bundle = folder / manifest['bundle']
    if bundle.is_symlink():
        stop('bundle.location', 'bundleのsymbolic linkは受理しません')
    if not bundle.is_file():
        stop('bundle.exists', 'bundleがありません')
    if bundle.resolve().parent != folder:
        stop('bundle.location', 'bundleが指定folder外を参照しています')
    if bundle.stat().st_size > MAX_BUNDLE_BYTES:
        stop('bundle.size', 'Stage +2Aの処理上限を超えています。bundle不正ではありません',
             MAX_BUNDLE_BYTES, bundle.stat().st_size)

    remote_url = test_remote_url or f'https://github.com/{manifest["repository"]}.git'
    with tempfile.TemporaryDirectory(prefix='dksc-verifier-') as temp:
        repo = Path(temp)
        snapshot = repo / 'verified.bundle'
        actual_hash = sha256_file(bundle, snapshot=snapshot)
        if actual_hash != manifest['bundleSha256']:
            stop('bundle.sha256', 'SHA256不一致のためGitにbundleを渡しません',
                 manifest['bundleSha256'], actual_hash)
        bundle = snapshot

        for key in ('baseBranch', 'branch'):
            git_checked('manifest.' + key + '.gitRef',
                        ['check-ref-format', '--branch', manifest[key]], cwd=repo)
        # 既存repositoryやtemplate由来の設定・hook・checkoutには触れません。
        git_checked('temp.gitInit', ['init', '--bare', '--template=', '--object-format=sha1', '-q', str(repo)])
        git_checked('bundle.verify', ['-C', str(repo), 'bundle', 'verify', str(bundle)])
        git_checked('remote.add', ['-C', str(repo), 'remote', 'add', 'origin', remote_url])
        actual_url = git_checked('remote.url', ['-C', str(repo), 'config', '--local',
                                             '--get', 'remote.origin.url']).strip()
        if actual_url != remote_url:
            stop('remote.url', 'originが生成したURLと一致しません')
        git_checked('base.fetch', ['-C', str(repo), 'fetch', '--no-tags', 'origin',
                 f'refs/heads/{manifest["baseBranch"]}:refs/dksc/base'])
        main = single_ref('base.head', git_checked('base.head',
                 ['-C', str(repo), 'rev-parse', '--verify', 'refs/dksc/base^{commit}']))
        if main != manifest['expectedMain']:
            stop('base.head', 'baseのHEADが想定と異なります', manifest['expectedMain'], main)

        git_checked('bundle.fetch', ['-C', str(repo), 'fetch', '--no-tags', str(bundle),
                    f'refs/heads/{manifest["branch"]}:refs/dksc/bundle'])
        git_checked('bundle.objects', ['-C', str(repo), 'fsck', '--strict', '--no-reflogs'])
        head = single_ref('bundle.head', git_checked('bundle.head',
                 ['-C', str(repo), 'rev-parse', '--verify', 'refs/dksc/bundle^{commit}']))
        if head != manifest['expectedHead']:
            stop('bundle.head', 'bundle内HEADが想定と異なります', manifest['expectedHead'], head)

        ancestor = git(['-C', str(repo), 'merge-base', '--is-ancestor', main, head], allow_failure=True)
        if ancestor.returncode != 0:
            stop('history.ancestor', 'baseがHEADのancestorではありません', f'{main} → {head}',
                 f'exit {ancestor.returncode}')

        file_output = git_checked('diff.files', ['-C', str(repo), 'diff', '--name-only', '-z',
                f'{main}...{head}', '--'])
        # Preserve path whitespace: -z emits raw NUL-separated Git names.
        actual_files = [x for x in file_output.split('\x00') if x]
        if sorted(actual_files) != sorted(manifest['expectedFiles']):
            stop('diff.files', '変更ファイルの集合が一致しません',
                 json.dumps(sorted(manifest['expectedFiles']), ensure_ascii=False),
                 json.dumps(sorted(actual_files), ensure_ascii=False))
        git_checked('diff.check', ['-C', str(repo), 'diff', '--check', f'{main}...{head}', '--'])

        commits_output = git_checked('history.commits', ['-C', str(repo), 'rev-list',
                          '--reverse', f'{main}..{head}'])
        commits = [line.lower() for line in commits_output.splitlines() if line]
        if manifest['expectedCommits'] and commits != manifest['expectedCommits']:
            stop('history.commits', 'commit件数・順序・SHAが一致しません',
                 json.dumps(manifest['expectedCommits']), json.dumps(commits))

        remote_state = remote_branch_state(repo, manifest['branch'], head)
        # Stage +2 has no push/PR/merge. Only temporary local ref creation is performed.
        return {
            'status': 'PASS', 'stage': '+2', 'mode': 'read-only',
            'verificationLevel': 'full' if manifest['expectedCommits'] else 'partial',
            'fullyVerified': bool(manifest['expectedCommits']),
            'warnings': [] if manifest['expectedCommits'] else [
                'expectedCommitsが空のためcommit列の完全一致は未検証です'],
            'release': manifest['release'], 'repository': manifest['repository'],
            'branch': manifest['branch'], 'expectedMain': main,
            'expectedHead': head, 'bundleSha256': actual_hash,
            'changedFiles': actual_files, 'commits': commits,
            'commitsFullyChecked': bool(manifest['expectedCommits']),
            'remoteBranch': remote_state, 'remoteWriteCount': 0,
        }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('Usage: python tools/verify_bundle.py /path/to/release-folder', file=sys.stderr)
        return 2
    try:
        output = verify(Path(argv[1]))
    except StopVerification as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 1
    except OSError:
        print(json.dumps(StopVerification('input.io', 'ファイルまたは一時領域の操作に失敗しました').as_dict(),
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
