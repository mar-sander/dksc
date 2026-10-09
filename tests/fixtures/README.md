# 公開用の人工fixture

`dksc-stage-plus1-android-test.bundle` と `publish-manifest.json` は、添付された
Stage +2 draftの小型試験データです。開発中の製品bundleではありません。

テストはこのbundleからローカルbare remoteを作ります。GitHub通信・pushは行いません。
ancestor不一致、diff空白エラーなどは、各テストの一時領域内で実Git履歴を生成します。
時刻により派生commitのSHAは変わりますが、期待値はその実履歴から取得するため判定は再現できます。
