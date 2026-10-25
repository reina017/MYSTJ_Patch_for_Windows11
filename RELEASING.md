# GitHub頒布手順

この `mystj-win11-patch` フォルダーだけをGitリポジトリにします。親フォルダー・私用調査フォルダー・導入済みMYSTJは公開しません。

1. `py -3 test_mystj.py` で隔離したテストを実行します。
2. `py -3 build_release.py` で独自ランチャー入りパッチZIPとSHA-256を作成します。
3. `py -3 build_release.py --audit` と `git ls-files` で公開対象を確認します。許可リスト以外は追加できません。
4. GitHubの公開リポジトリへソースのみ登録し、`v0.1.0-beta.1` タグを作成します。
5. GitHub Releaseをpre-releaseとして作り、`dist/mystj-win11-patch-0.1.0-beta.1.zip` と `.zip.sha256` を添付します。

製品のDAT・MOV・画像・旧インストーラー・ScummVM ZIP/展開済みruntime・設定・セーブデータを追加してはいけません。独自ランチャー以外のEXE/DLLは配布しません。
GitHub自動生成のSource code ZIPには独自ランチャーEXEがないため、一般利用者にはReleaseの配布ZIPを案内します。

手元のCDを使った統合テスト例:

```bat
py -3 test_mystj.py --media F:\ --runtime-zip C:\Downloads\scummvm-2026.4.0-win32-x86_64.zip --assets C:\PatchExtract\mystj-win11-patch-0.1.0-beta.1
```

このテストは一時フォルダーへ導入し、設定を残す削除・再導入・完全削除を行います。レジストリはFakeRegistryに置き換え、実ユーザーのアプリ一覧には登録しません。

公開名の例: **MYST 日本語版 Windows 11 対応化パッチ v0.1.0-beta.1**。
説明に「CD-ROM所有者向け・非公式・ScummVMによる実行環境セットアップ・製品データなし」と明記します。
