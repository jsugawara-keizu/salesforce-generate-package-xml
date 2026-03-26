# Changelog

このプロジェクトのすべての変更履歴を記載します。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、
バージョン管理は [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

## [1.0.3] - 2026-03-26

### 追加

- README に GitHub Actions ワークフローのサンプル全文を掲載 (JWT 認証 → package.xml 生成 → retrieve → コミット)
- README に参考リンクセクションを追加 (Salesforce 公式ドキュメント / 関連 GitHub リポジトリ / バージョン管理規約)

## [1.0.2] - 2026-03-25

### 変更

- `_TRACKED_LIMITS` / `_process_explicit` / `_process_folder` のアンダースコアプレフィックスを削除 (public シンボルとして命名を統一)

### 修正

- CHANGELOG.md の `[1.0.0]` リンクが重複していたバグを修正

## [1.0.1] - 2026-03-25

### 追加

- `docs/examples/daily-tracking.yml` を実運用に基づき改善
  - 認証方式を外部クライアントアプリケーション + JWT Bearer フローに変更
  - IP アドレス制限の回避方法 (連携専用プロファイル/ユーザー) を注記
  - `git stash → pull → stash pop` で並行コミットに対応
  - `package*.xml` を `for` ループで retrieve し、分割ファイルに対応

### 修正

- v1.0.0 の CHANGELOG エントリが空だったため内容を追記

## [1.0.0] - 2026-03-25

### 追加

- `--include-types TYPE` / `--exclude-types TYPE`: 取得対象タイプの絞り込み・除外オプション
- `--list-types`: org のメタデータタイプ一覧を表示して終了するオプション
- `--output-dir DIR`: 出力先ディレクトリ指定オプション
- `--summary-json PATH`: 実行結果サマリ (タイプ別メンバー数・生成日時) の JSON 出力オプション
- `--version`: バージョン表示オプション
- `--log-file PATH`: ログをファイルにも同時出力するオプション
- Metadata API コール数 (`DailyMetadataApiRequests`) の使用状況表示 (組織設定により表示されない場合あり)
- pytest-cov によるテストカバレッジ計測 (CI でカバレッジレポートを自動生成)
- Windows 向けインストール手順を README に追加
- `docs/examples/daily-tracking.yml`: 実運用に基づく改善
  - 認証方式を外部クライアントアプリケーション + JWT Bearer フローに変更
  - IP アドレス制限の回避方法 (連携専用プロファイル/ユーザー) を注記
  - `git stash → pull → stash pop` で並行コミットに対応
  - `package*.xml` を `for` ループで retrieve し、分割ファイルに対応

### 変更

- ログ出力を `print` / `tprint` / `_print_lock` から `logging` モジュールに移行
  - すべての出力にタイムスタンプとログレベルが付与される (`2026-03-25 12:00:00 INFO ...`)
  - `--verbose` が DEBUG ログレベルとして機能するよう変更
- `get_org_api_version`: `apiVersion` フィールドを優先取得し、`instanceApiVersion` にフォールバック (新旧 SF CLI 両対応)
- オプション一覧テーブルを README に追記 (`--output-dir`, `--summary-json`, `--log-file` など)

### 修正

- `get_org_api_version`: `result` フィールドが `null` のとき AttributeError が発生するバグを修正
- `get_org_api_version`: `apiVersion` が int 型のとき `instanceApiVersion` が無視されるバグを修正
- `_setup_logging`: `--log-file` に無効なパスを指定したとき生のトレースバックが出るバグを修正 (OSError を捕捉してユーザー向けメッセージを表示)
- `_on_complete` と `_on_folder_done` の進捗カウンタ更新を同一ロックで保護 (スレッド競合を解消)

## [0.2.0] - 2026-03-24

### 追加

- `--api-version` 省略時に org から API バージョンを自動取得する機能 (`get_org_api_version`)
- リリース自動化ワークフロー
  - `bump-version.yml`: Actions タブから手動実行してバージョン更新・タグ作成を自動化
  - `release.yml`: タグ push をトリガーに CHANGELOG.md からリリースノートを抽出して GitHub Release を自動作成
- GitHub Actions CI ワークフロー (lint / test / type-check)
- `tests/test_metadata.py`: `get_org_api_version()` のユニットテスト 6件

### 変更

- `--api-version` のデフォルト値を `62.0` から org 自動取得に変更 (取得失敗時は `62.0` にフォールバック)
- インストール方法の推奨を `pipx` に変更 (README 更新)

## [0.1.0] - 2026-03-24

### 追加

- Salesforce org の全メタデータを網羅した `package.xml` を自動生成する機能
- 特殊タイプへの対応
  - `StandardValueSet`: GitHub から最新メンバー一覧を自動取得
  - `Settings` 系 (`AccountSettings` 等): `*` を自動セット
  - フォルダ型 (`Report` / `Dashboard` / `Document` / `EmailTemplate`): フォルダ一覧取得 → コンテンツ取得の2段階処理
- 管理パッケージの除外オプション (`--exclude-all-namespaces` / `--exclude-namespace NS`)
- `ThreadPoolExecutor` による並列取得 (`--workers N`、デフォルト 8)
- メンバー総数が retrieve 上限 (10,000件) を超える場合の自動分割 (`--max-members N`)
- ワイルドカードモード (`--wildcard`)
- フォルダ型除外オプション (`--skip-folders`)
- API コール数の使用状況表示 (開始時・終了時・今回の消費数)
- スロットルエラー時の exponential backoff リトライ
- `src/` レイアウトによるパッケージ構成
  - `sf_package_xml.filters` — 名前空間フィルタリング
  - `sf_package_xml.metadata` — SF CLI ラッパー / 並列取得
  - `sf_package_xml.xml_builder` — package.xml 生成・分割
  - `sf_package_xml.cli` — CLI エントリーポイント
- CLI コマンド `sf-package-xml` および `python -m sf_package_xml` での実行
- pytest による 53 ユニットテスト (filters / xml_builder)
- MIT ライセンス

[Unreleased]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/releases/tag/v0.1.0
