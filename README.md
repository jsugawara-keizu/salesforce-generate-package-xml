# sf-package-xml

[![CI](https://github.com/jsugawara-keizu/salesforce-generate-package-xml/actions/workflows/ci.yml/badge.svg)](https://github.com/jsugawara-keizu/salesforce-generate-package-xml/actions/workflows/ci.yml)

> [!NOTE]
> このリポジトリは Python パッケージ開発・GitHub Actions CI・ブランチ運用などを学ぶための**練習・検証目的**で作成したものです。
> 本番環境での利用は想定していません。

Salesforce org に存在するすべてのメタデータを網羅した `package.xml` を自動生成する Python ツールです。

## 機能

- **全メタデータを網羅**: `sf org list metadata-types` で取得できるすべてのタイプを対象に、メンバーを自動列挙します
- **特殊タイプへの対応**
  - `StandardValueSet`: SF CLI が空を返す仕様のため GitHub から最新メンバー一覧を自動取得
  - `Settings` 系 (`AccountSettings` 等): `*` を自動セット
  - フォルダ型 (`Report` / `Dashboard` / `Document` / `EmailTemplate`): フォルダ一覧取得 → コンテンツ取得の2段階で対応
- **管理パッケージの除外**: `--exclude-all-namespaces` / `--exclude-namespace NS` で名前空間付きコンポーネントを除外
- **並列取得**: `ThreadPoolExecutor` による高速化 (デフォルト 8 ワーカー)
- **自動分割**: メンバー総数が Salesforce の retrieve 上限 (10,000件) を超える場合、`package_01.xml` / `package_02.xml` … に自動分割

## 動作要件

- Python 3.10 以上
- [Salesforce CLI (`sf`)](https://developer.salesforce.com/tools/salesforcecli) がインストール済みであること
- 対象 org が `sf org login` で認証済みであること
- 実行環境から `raw.githubusercontent.com` へのアクセスが可能であること (StandardValueSet の取得に使用)
- 実行ユーザーが対象 org で Metadata API の読み取り権限を持つこと (システム管理者プロファイル推奨)

## インストール

### pipx を使う方法 (推奨)

[pipx](https://pipx.pypa.io/) は CLI ツール専用の隔離環境を自動管理するツールです。
SFDXプロジェクトを汚さずにグローバルで使えるため、通常の利用にはこちらを推奨します。

**macOS**

```bash
# pipx 自体のインストール (未インストールの場合)
brew install pipx
pipx ensurepath

# sf-package-xml をインストール
pipx install git+https://github.com/jsugawara-keizu/salesforce-generate-package-xml.git
```

**Windows (PowerShell)**

```powershell
# pipx 自体のインストール (未インストールの場合)
pip install pipx
pipx ensurepath
# ターミナルを再起動して PATH を反映

# sf-package-xml をインストール
pipx install git+https://github.com/jsugawara-keizu/salesforce-generate-package-xml.git
```

インストール後はどのディレクトリからでも実行できます:

```bash
sf-package-xml -o myOrg
```

アップデートする場合:

```bash
pipx upgrade sf-package-xml
```

### pip を使う方法

プロジェクトの仮想環境に組み込む場合や、開発目的の場合はこちら。

**macOS / Linux**

```bash
git clone https://github.com/jsugawara-keizu/salesforce-generate-package-xml.git
cd salesforce-generate-package-xml
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/jsugawara-keizu/salesforce-generate-package-xml.git
cd salesforce-generate-package-xml
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

または `python -m sf_package_xml` でも実行できます:

```bash
python -m sf_package_xml -o myOrg
```

## 使い方

```bash
# 基本 (全メタデータを取得)
sf-package-xml -o myOrg

# フォルダ型を除外して高速化
sf-package-xml -o myOrg --skip-folders

# 管理パッケージコンポーネントを除外
sf-package-xml -o myOrg --exclude-all-namespaces

# 特定の名前空間を除外
sf-package-xml -o myOrg --exclude-namespace FSJP acme

# 16並列で高速実行 + 詳細ログ
sf-package-xml -o myOrg --workers 16 --verbose

# ワイルドカードモード (個別メンバーを列挙しない)
sf-package-xml -o myOrg --wildcard --output manifest/package.xml

# 5000件ごとに分割
sf-package-xml -o myOrg --max-members 5000
```

## オプション一覧

| オプション | デフォルト | 説明 |
|---|---|---|
| `-o`, `--target-org` | デフォルト org | 対象 org のエイリアスまたはユーザー名 |
| `-v`, `--api-version` | org から自動取得 | Metadata API バージョン |
| `--output` | `package.xml` | 出力ファイルパス |
| `--output-dir DIR` | - | 出力先ディレクトリ。指定時は `--output` のファイル名をそのまま使用 |
| `--wildcard` | - | 全タイプを `*` で出力する高速モード |
| `--skip-folders` | - | フォルダ型メタデータ 4タイプを除外 |
| `--verbose` | - | 取得したメンバー名を1件ずつ表示 (DEBUG ログレベル) |
| `--log-file PATH` | - | ログをファイルにも出力する |
| `--exclude-namespace NS` | - | 除外する名前空間プレフィックス (複数指定可) |
| `--exclude-all-namespaces` | - | 全名前空間付きメンバーを除外 |
| `--workers N` | `8` | 並列ワーカー数 |
| `--max-members N` | `10000` | 1ファイルあたりの最大メンバー数 |
| `--include-types TYPE` | - | 取得対象タイプを指定 (複数指定可)。指定したタイプのみ取得 |
| `--exclude-types TYPE` | - | 除外するタイプを指定 (複数指定可)。`--skip-folders` の汎用版 |
| `--list-types` | - | org のメタデータタイプ一覧を表示して終了 |
| `--summary-json PATH` | - | 実行結果のサマリ (タイプ別メンバー数・生成日時等) を JSON に出力 |

## GitHub Actions との連携

`package.xml` の日次自動生成 + メタデータ取得 + git コミットのパイプラインに組み込む場合の例:

```yaml
name: Retrieve Metadata

on:
  workflow_dispatch:  # 手動実行
  schedule:
    - cron: '0 0 * * *'  # 毎日 UTC 0:00 (JST 9:00) に自動実行

jobs:
  retrieve:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Install Salesforce CLI
        run: npm install -g @salesforce/cli

      - name: Install sf-package-xml
        run: pip install git+https://github.com/jsugawara-keizu/salesforce-generate-package-xml.git

      - name: Authenticate to Salesforce via JWT
        run: |
          echo "${{ secrets.SF_PRIVATE_KEY }}" > server.key
          sf org login jwt \
            --client-id "${{ secrets.SF_CONSUMER_KEY }}" \
            --jwt-key-file server.key \
            --username "${{ secrets.SF_USERNAME }}" \
            --instance-url "${{ secrets.SF_INSTANCE_URL }}" \
            --set-default \
            --alias my-org
          rm -f server.key

      - name: Generate package.xml
        run: |
          sf-package-xml \
            --target-org my-org \
            --output manifest/package.xml

      - name: Retrieve metadata
        run: |
          retrieve_with_retry() {
            local manifest="$1"
            local max_attempts=10
            local attempt=0
            while [ $attempt -lt $max_attempts ]; do
              attempt=$((attempt + 1))
              echo "Retrieving (attempt ${attempt}): ${manifest}"
              if error_output=$(sf project retrieve start \
                --manifest "${manifest}" \
                --target-org my-org 2>&1); then
                echo "${error_output}"
                return 0
              fi
              echo "${error_output}"
              unsupported_type=$(echo "${error_output}" | grep -oP "(?<=Entity of type ')[^']+" | head -1)
              if [ -z "${unsupported_type}" ]; then
                unsupported_type=$(echo "${error_output}" | grep -oP "(?<=No type named: )\S+" | head -1)
              fi
              if [ -z "${unsupported_type}" ]; then
                unsupported_type=$(echo "${error_output}" | grep -oP "(?<=for id ')[^']+" | head -1)
              fi
              if [ -z "${unsupported_type}" ]; then
                echo "復旧不可能なエラー (未サポートタイプを特定できません)。処理を終了します。"
                return 1
              fi
              echo "未サポートタイプ '${unsupported_type}' を ${manifest} から除外します"
              python3 docs/examples/remove_unsupported_type.py "${manifest}" "${unsupported_type}"
            done
            echo "最大リトライ回数 (${max_attempts}) に達しました。処理を終了します。"
            return 1
          }

          for pkg in manifest/package*.xml; do
            retrieve_with_retry "$pkg"
          done

      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git stash
          git pull --rebase origin main
          git stash pop
          git add force-app/ manifest/package*.xml
          git diff --staged --quiet || git commit -m "chore: retrieve metadata [skip ci]"
          git push
```

必要な GitHub Secrets:

| Secret | 内容 |
|---|---|
| `SF_CONSUMER_KEY` | 外部クライアントアプリケーションのクライアント ID |
| `SF_PRIVATE_KEY` | JWT 署名用秘密鍵 (PEM 形式の内容をそのまま登録) |
| `SF_USERNAME` | 連携専用ユーザーのユーザー名 |
| `SF_INSTANCE_URL` | org の URL (`https://login.salesforce.com` または Sandbox URL) |

> **IP アドレス制限がある場合**: GitHub Actions の実行 IP は固定されないため、連携専用プロファイルで「IP アドレスの制限なし」を設定した専用ユーザーで実行してください。

詳細なサンプルは以下を参照してください:

- [docs/examples/daily-tracking.yml](docs/examples/daily-tracking.yml) — 完全なワークフロー定義
- [docs/examples/remove_unsupported_type.py](docs/examples/remove_unsupported_type.py) — リトライ時に未サポートタイプを package.xml から除外するヘルパースクリプト

終了コード:
- `0`: 完全成功
- `1`: 致命的エラー (org 接続失敗等)
- `2`: 部分的失敗 (一部タイプの取得失敗、`package.xml` は生成済み)

## 開発

```bash
# 依存関係のインストール
pip install -e ".[dev]"

# テスト実行
pytest
```

## 参考リンク

### Salesforce 公式ドキュメント

| リンク | 内容 |
|---|---|
| [Metadata API Developer Guide](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/) | Metadata API の全タイプ・制約の公式リファレンス |
| [package.xml マニフェストファイル](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/manifest_files.htm) | package.xml の書式・記法の説明 |
| [Salesforce CLI コマンドリファレンス](https://developer.salesforce.com/docs/atlas.en-us.sfdx_cli_reference.meta/sfdx_cli_reference/cli_reference_unified.htm) | `sf org list metadata` 等のコマンド仕様 |

### GitHub リポジトリ

| リポジトリ | 内容 |
|---|---|
| [forcedotcom/source-deploy-retrieve](https://github.com/forcedotcom/source-deploy-retrieve) | Salesforce CLI のメタデータ操作ライブラリ。`StandardValueSet` のメンバー一覧 (`stdValueSetRegistry.json`) の取得元 |
| [forcedotcom/cli](https://github.com/forcedotcom/cli) | Salesforce CLI (`sf`) 本体 |

### バージョン管理・変更履歴

| リンク | 内容 |
|---|---|
| [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) | CHANGELOG.md のフォーマット規約 |
| [Semantic Versioning](https://semver.org/lang/ja/) | バージョン番号の付け方 (MAJOR.MINOR.PATCH) |

### Salesforce リリーススケジュール

Salesforce は年3回 (Spring / Summer / Winter) メジャーリリースを行い、新しいメタデータタイプが追加されることがあります。
このツールが参照する `stdValueSetRegistry.json` も各リリースで更新されますが、毎回 GitHub から最新版を取得するため常に最新状態を反映します。

## ライセンス

MIT
