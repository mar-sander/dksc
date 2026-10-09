# Windows Ver.1.0との検証規則対応

2026-10-09に取得した現行資料を直接読んで照合しました。元のWindowsファイルは変更していません。

| 資料 | 版・SHA256 |
| --- | --- |
| `dokodemo-publish.ps1` | version 2、2026-08-24更新。`7fc81ec370fb3ba9d87a79c63e82e66d4aacb2f0dd8d2459a59074bd9940b0c8` |
| `README_DOKODEMO.md` | version 3。`5100136a7a4aa9fbb85338b8941680705a731a7c54b9ab0cc66256b2a0772775` |
| `dokodemo-script-ver-1.0.zip` | version 3。`bcda86ebde58af01180db004e1bdbdeb55447f59ed578952737c7111a281ab2d` |

以下は**実装規則の照合**です。Windows PowerShell 5.1が今回の実行環境にないため、
Windows版を動かした同一fixture比較・Windows端末での実行は未検証です。

| 検証項目 | Windows Ver.1.0 | +2A | 対応・差異 |
| --- | --- | --- | --- |
| manifest形式 | 8必須文字列・2必須配列、1 MiB、BOM可 | 同じfieldと上限、BOM可 | 主規則対応。JSON parser差は網羅未検証 |
| repository | owner/repoのみ、HTTPS GitHub URL生成 | 同じ | 対応。+2Aはcredentialなし・公開repo限定 |
| branch | base同名/main拒否、check-ref-format | 同じ | 対応 |
| SHA形式 | commit40桁、SHA25664桁 | 同じ | 対応。SHA-256形式Git repositoryは対象外 |
| bundle filename・場所 | Windows安全名、同一folder | 同じ安全名、link拒否 | +2Aは制御文字も明示拒否。Windows filesystem条件は全件未検証 |
| bundle hash | SHA256一致前にGitへ読ませない | 同じ＋照合したcopyを利用 | 対応。TOCTOU防止を追加 |
| bundleサイズ | 固定上限なし | 256 MiB | 処理上限の差。Android Stage +1は64 MiBのまま |
| bundle verify | 空の一時repoで検証 | 空の一時bare repoで検証 | self-contained必須。増分bundleはSTOP |
| origin URL | local configの生成URLを再照合 | 同じ | 対応 |
| expectedMain | base fetch後のcommit HEAD照合 | 同じ | 不一致はbase.head STOP |
| expectedHead | bundle指定branchのcommit HEAD照合 | 同じ | 不一致はbundle.head STOP |
| object健全性 | fetchに従う | fetch後fsck --strictを追加 | +2Aは厳格化。古い不正objectを追加で拒否する可能性 |
| ancestor | merge-base --is-ancestor | 同じ | history.ancestor STOP |
| diff files | main...headのname-only、順序無視・完全一致 | 同じrange、NUL区切り | +2Aは日本語・空白を生pathで比較。Windowsのquoted path出力とは差異あり |
| diff --check | exit code非0でSTOP | 同じ | diff.check STOP。+2Aはソース本文を結果へ出さない |
| commit列 | rev-list --reverse、件数・順序・SHA一致 | 同じ | history.commits STOP |
| 空expectedCommits | 受理・WARN・完全一致省略 | 受理・partial・fullyVerified:false・WARN | 意味は対応。完全検証表示を明確化 |
| remote同名branch | 無し／同HEAD／別HEADでSTOP | 同じ | 別HEADはremote.branch.head STOP |
| 二重実行 | 同HEADなら再pushしない | 同じ結果、全経路でpushなし | remoteと入力のbytes不変を2回実行で確認 |
| local branch/checkout/clean | branch作成・checkout・HEAD/status確認 | 行わない | 意図的差。検証済みrefを扱い、checkout filter等を実行しない |
| 認証・環境設定 | 既存credential/configを利用、変更しない | 持込Git設定・credentialを抑止 | 意図的差。private repo動作は未対応 |
| Git stderr | exit code 0なら正常として扱う | 同じ | Pythonはexit codeで判定。失敗の生出力は非表示 |
| 一時領域 | 所有marker確認してfinallyで削除 | TemporaryDirectoryで削除 | PASS/STOP両方の削除をfixture確認。強制終了は別設計 |
| push前承認・push後remote照合 | 通常公開時に実施、DryRunは省略 | 未実装 | +2Aは公開処理を持たない。公開可能・公開済みの証明ではない |

テストは人工bundleとlocal bare remoteだけを使用します。Windows版の全テストキット相当や
実GitHub targetへの検証を行ったとは主張しません。正式な比較実行は次段階の条件です。
