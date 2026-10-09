# Stage +2B：Android WEB UIとGit実行環境の接続設計

2026-10-09時点の調査・設計です。接続実装、外部サービス契約、ユーザー認証連携、鍵発行は行っていません。
下記の保持時間、実行枠、容量、予算は**提案値**です。

## 結論

Android完結とGit CLIとの意味論の一致を優先するなら、**private一時保存＋認証付き受付API＋
隔離Git runner**を推奨します。公開DKSCのActionsには、人工fixtureによる今回のテストだけを置きます。
本番の未公開bundle・検証結果は公開repositoryや公開ログへ渡しません。

ただし外部クラウド・認証・費用の決定が必要です。指示書§4に従い、この案は設計段階でSTOPします。
費用ゼロ・ファイルを端末外へ出さないことを最優先する場合は、WASMの小型fixture実証を先に行う選択があります。
現時点ではどちらもAndroid上で完成済みとは扱いません。

## 方式比較

| 方式 | ファイル搬送と結果取得 | 保持・アクセス制御 | 費用 | 運用・未解決点 |
| --- | --- | --- | --- | --- |
| private bucket＋private Actions | multipart upload後にAPIでjob起動。dispatchにはjob IDだけ渡す。結果は認証APIから取得 | bucket非公開、短命URL、所有者ごとのjob。Actions側もprivate | 保存・request・API・Actions計算時間。S3は構成により通信料金も加算 | サービスとGitHubの2系統の権限管理。Actions起動用資格情報が必要。artifact/logへbundleを残さない設計が必要 |
| private bucket＋隔離runner（推奨） | R2/S3へ分割upload。APIのqueueからrunnerが取得。結果は認証APIでpoll | 非公開bucket＋job所有者＋runner専用権限。成功/STOPとも削除 | 保存・request・API・runner。R2はegress無料だが総費用が無料になる保証はない | Git CLIコアを再利用できる。queue、隔離、削除監視、更新管理を運用する必要あり |
| 自前serverへ直接upload | 認証APIがstreamで受け取り、一時volumeのGitへ渡す | HTTPS、所有者制御、短期volume。結果は同じAPI | 既存設備があれば追加契約を抑えられる。電気・回線・保守は必要 | 公開endpoint、TLS、OS更新、容量・同時実行制限、Android再送処理を自分で管理。常時稼働が前提 |
| ブラウザ内WASM | bundleを端末内で処理。remote観測は別途通信 | bundleのserver保存なし | server計算・保存費用は不要になり得る。開発・配信費用は残る | Git bundle/pack/objects/ancestor/diff/check/orderの同等実装、CORS、Android memory・storage、WASM中断制御が未実証 |

`workflow_dispatch`入力の上限は65,535文字です。base64搬送はさらに膨らむためbundle本体には使いません。
起動APIは認証が必要で、fine-grained tokenではActions writeが必要です。[1][2]
今回のCIはcontents readのみです。本番Actions起動権限をこのCIへ追加する案ではありません。
workflow_dispatchはdefault branchにworkflowが存在する条件もあるため、新branchから未承認で接続しません。[1]

isomorphic-gitの公開command一覧ではGit bundle verify APIを確認できませんでした。[7]
これは「WASMなら不可能」という証明ではありませんが、簡略Git判定を完全検証として採用できる根拠もありません。
実Git CLIとの差分試験を全fixtureで通すまで、WASM結果は実験扱いです。

## 推奨案の処理と保護

1. 認証済みユーザーが受付APIへmanifestとサイズを提示し、所有者に紐づくjob IDを取得します。
   bundle名やrepository名をbucket keyに使わず、推測困難な内部IDで保存します。
2. APIが限定object用の短命upload権限を発行し、Chromeがmultipart uploadします。
   資格情報はserver側だけに置きます。CORSはDKSC originだけを許可しますが、CORSを認証の代わりにはしません。
3. 完了後にobject versionとSHA256を固定し、書換不能なjob入力としてrunnerへ渡します。
   署名URLは期限内に複数回使用可能なので、URLの失効だけで書換防止が完成したと扱いません。[3][5]
4. 資格情報を持たない隔離runnerが+2Aコアを実行します。private bucketからの取得は別の搬送役が行います。
   Git実行中の通信先はGitHub読み取りに限定。ユーザーbundleから任意URL、shell command、workflowを生成しません。
5. 認証APIが最小のJSON結果を返します。job IDだけで第三者が読めるURLは作りません。
   `fullyVerified`と検証stageを表示し、静的PASS・部分PASS・Git完全照合・STOPを区別します。
6. 成功/STOP/timeoutで入力・展開領域を削除します。削除失敗なら非公開隔離と運用通知を行い、
   削除済みとは表示しません。確認可能な削除状態をjob metadataへ残します。

## 保持・制限の提案

| 対象 | 提案 |
| --- | --- |
| upload/download権限 | 10分。期限更新は所有者を再確認。URLをログ・dispatch入力へ出さない |
| 入力bundle | 処理終了時に削除。未完了jobも24時間以内にserver監視で削除 |
| 未完了multipart | 24時間のabort監視。bucket lifecycleは長期残存に備えた補助 |
| 結果JSON | 24時間以内、所有者だけ閲覧。必要なら所有者が端末へ保存 |
| audit metadata | 7日案。job状態・容量・時間だけ。ソース、URL、認証情報を記録しない |
| 入力上限 | 初期256 MiB案。multipartは搬送制限を緩和しても無制限処理を意味しない |
| 実行枠 | 1ユーザー同時1件、job 10分案。CPU・memory・disk・展開総量・Git出力量も制限 |
| 強制終了 | process group停止＋ephemeral volume廃棄。残存隔離領域を定期掃除 |

private bucketのlifecycleと署名URLの失効は別です。URLが失効しても保存objectは消えません。
S3ではmultipartは完了またはabortが必要で、未完了partsにも保管料金が発生します。[4]
R2の未完了multipart既定abortは7日なので、24時間案は追加監視・設定が必要です。[6]

「任意サイズ」は、ユーザーが任意のbundleを選べることと、容量無制限を区別します。
上限超過は不正ファイルとせず、処理能力によるSTOPとします。Stage +1の64 MiB上限の変更は別Stageです。

## 費用の比較と決定事項

R2 Standardの公表単価は保存$0.015/GB-month、Class A $4.50/百万件、Class B $0.36/百万件、
internet egressは無料です。無料枠・丸め・API/runner・認証・ログ費用は別途考慮が必要です。[8]
S3案はregion・保存class・通信先に依存するため、この段階で固定の月額を約束しません。[9]

概算は「平均保存GB × 保存単価 ＋ request数 × 単価 ＋ API/認証 ＋ runner時間 ＋ 通信」です。
短期保管なら保存料よりrunnerと運用費が支配的になる可能性があります。これは設計上の推測です。
利用件数・最大サイズ・保持時間・既存契約が未確定なので、総月額は未確定です。

次の実装を依頼する際に決める内容は、端末外への一時転送を許可するか、既存server/cloudがあるか、
月額上限、利用者がNo.Mだけか複数か、最大bundle容量、private GitHub repoも対象か、の6点です。
private repoを対象にする場合は認証用の別設計が必要で、このStageのコアが対応済みとは扱いません。

## 一次資料（2026-10-09確認）

1. [GitHub workflow events / workflow_dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
2. [GitHub REST workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
3. [S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
4. [S3 multipart upload](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)
5. [R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
6. [R2 upload / multipart](https://developers.cloudflare.com/r2/objects/upload-objects/)
7. [isomorphic-git commands](https://isomorphic-git.org/docs/en/alphabetic)
8. [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
9. [S3 pricing](https://aws.amazon.com/s3/pricing/)

これらは公開仕様の確認資料です。DKSCとの接続・Android実機動作・費用請求を実証した資料ではありません。
