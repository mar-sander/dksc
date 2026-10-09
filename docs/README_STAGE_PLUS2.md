# DKSC Stage +2A：読み取り専用Git検証

Stage +1のWEB画面を維持したまま、添付draftのPython + Git CLIコアを独立追加しました。
**Android WEB UIとは未接続です。** このbranchをmergeしない限りmainの公開内容は変わりません。

## 実行

Python 3.10以上とGitが必要です。コアのPython外部依存はありません。

```sh
python tools/verify_bundle.py /path/to/release-folder
python -m unittest discover -s tests -p 'test_stage2.py' -v
node --test tests/test_stage1.mjs
```

release-folderには`publish-manifest.json`とmanifestで指定した.bundleを置きます。
CLIは`https://github.com/<repository>.git`を生成します。任意URLオプションはありません。
`test_remote_url`はPython fixture試験にだけ使う内部入口で、公開サービスの入力にしてはいけません。
資格情報を利用しないため、非公開repositoryの検証はこのStageでは未対応です。

## 判定範囲

SHA256 → Git ref形式 → 空の一時repositoryで`git bundle verify` → remote base HEAD →
bundleのrefとHEAD → `git fsck --strict` → ancestor → 変更ファイル集合 →
`git diff --check` → `git rev-list --reverse`によるcommit列 → remote同名branchを照合します。
途中で失敗したらJSONのSTOPと終了コード1を返します。使用法の誤りは終了コード2です。

成功時は終了コード0とJSONを返します。**`status`だけで完全検証を判定しないでください。**

| 結果 | 意味 |
| --- | --- |
| `PASS`, `fullyVerified:true`, `verificationLevel:full` | +2Aの全照合を通過。公開承認やpush成功を意味しません |
| `PASS`, `fullyVerified:false`, `verificationLevel:partial` | Windows互換として空の`expectedCommits`を受理。commit完全一致は未検証 |
| `STOP` | 指定された検証条件または処理条件を満たせず停止 |

空の`expectedCommits`では`commitsFullyChecked:false`と`warnings`も返します。
Stage +1ブラウザPASSは従来どおり静的形式・filename・SHA256のみです。

## 修正と制限

- SHA256照合に使った同じbytesを一時コピーとしてGitへ渡します。入力ファイルを変更しません。
- bundleは256 MiB以下、manifestは1 MiB以下。超過は処理上限によるSTOPであり、bundle不正ではありません。
  Stage +1の64 MiB上限は変更していません。
- symbolic linkは同一folder内でも受理しません。
- `GIT_*`の持込設定、global/system config、credential helper、templates、hooksを抑止します。
  一時bare repositoryだけを更新し、checkout・push・PR・merge・tag・releaseは行いません。
- bundleはself-containedである必要があります。増分bundleは空repositoryでのverify時にSTOPします。
- Gitの生stderr・stdoutをSTOP結果に含めません。diffのソース本文やURLがログに出ることを防ぎます。
  成功結果のfile名・SHAも業務情報として扱い、将来のサービスでは公開ログへ記録しません。
- 不正UTF-8のGit出力は文字を置換せずSTOP。SHA-1の40桁commit schemaのみ対応します。
- Gitコマンドごとに120秒のtimeout。テストCIはjob全体10分。通常終了・例外では一時領域を削除します。
  強制終了やOS停止後の残存領域、圧縮展開量・stdout量・CPU/メモリ/ディスクの総量制限は、
  +2Bの隔離runnerと削除監視の設計事項です。256 MiB入力上限だけで解決した扱いにはしません。
- remote HEADは取得時の観測値です。検証後にremoteが変化しても自動追跡・再試行はしません。

## テスト専用CI

`.github/workflows/stage-plus2-tests.yml`はmainをbaseとする開発PRの変更時にfixture試験だけ実行します。
`permissions: contents: read`、checkoutの`persist-credentials:false`、actionのSHA固定を設定しています。
ユーザーbundle受付、workflow_dispatch、secret参照、artifact upload、Pages deployはありません。

Git検証36件、Stage +1回帰3件を実行します。Linux上の試験でありAndroid実機試験ではありません。
Windows PowerShell版を同一fixtureで実行した比較は未実施です。

規則対応は[WINDOWS_PARITY.md](WINDOWS_PARITY.md)、Android接続の設計比較は[STAGE_PLUS2B_DESIGN.md](STAGE_PLUS2B_DESIGN.md)を参照してください。
