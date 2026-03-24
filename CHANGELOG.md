# Changelog

このプロジェクトのすべての変更履歴を記載します。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、
バージョン管理は [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

## [0.2.0] - 2026-03-24

## [Unreleased]

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

[Unreleased]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jsugawara-keizu/salesforce-generate-package-xml/releases/tag/v0.1.0
