# どこでもスクリプト＋（DKSC）

どこにいても、どんなデバイスでも、使える。

Windows版「どこでもスクリプト」を維持しながら、Androidスマートフォン・タブレット・Windowsのブラウザから利用できるクロスデバイス版を開発します。

## Stage +1 — WEB Verifier（試作）

ブラウザ内だけで publish-manifest.json と完成 Git bundle（.bundle）を検証します。

- manifestのJSON・必須フィールド・形式確認
- bundleファイル名の照合
- SHA256計算・照合
- STOP理由、Expected、Actualを表示
- GitHubへの通信・認証・push・PR・merge・本番公開は一切しません

ブラウザ検証のPASSは **Git履歴の正当性も公開可否も保証しません**。Git bundle verify、HEAD、ancestor、diff、commit順序、remote同名branchの検証は次のStageに持ち越します。

Web Crypto のメモリ負荷を抑えるため、現行試作は64MiB以下のbundleに限定しています。超過をbundleの不正とは扱いません。

## 起動方法

HTTPSで配信したトップページ（GitHub Pages予定）にアクセスし、2ファイルを選択して「ローカル検証を実行」を押します。HTTPS/localhost以外ではWeb Cryptoを利用できない可能性があります。

GitHub Pagesを使う場合は、repository Settings → Pages → Build and deployment → Deploy from a branch → main / (root) を指定してください。

## セキュリティ原則

異常時は自動修復せずSTOPする。mainへの直接push・force push・認証情報の保存・人間承認の省略は行わない。Windows版やC Code Visualizer本体には変更を加えません。

このRepositoryのmainへの配置は「WEB画面のソース公開」であり、他Repositoryの完成branchをpushする操作とは異なります。
