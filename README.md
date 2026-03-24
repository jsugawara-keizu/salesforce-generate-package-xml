# sf-package-xml

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

```bash
# pipx 自体のインストール (未インストールの場合)
brew install pipx
pipx ensurepath

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

```bash
# リポジトリをクローン
git clone https://github.com/jsugawara-keizu/salesforce-generate-package-xml.git
cd salesforce-generate-package-xml

# 仮想環境を作成してインストール
python3 -m venv .venv
source .venv/bin/activate
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
| `-v`, `--api-version` | `62.0` | Metadata API バージョン |
| `--output` | `package.xml` | 出力ファイルパス |
| `--wildcard` | - | 全タイプを `*` で出力する高速モード |
| `--skip-folders` | - | フォルダ型メタデータ 4タイプを除外 |
| `--verbose` | - | 取得したメンバー名を1件ずつ表示 |
| `--exclude-namespace NS` | - | 除外する名前空間プレフィックス (複数指定可) |
| `--exclude-all-namespaces` | - | 全名前空間付きメンバーを除外 |
| `--workers N` | `8` | 並列ワーカー数 |
| `--max-members N` | `10000` | 1ファイルあたりの最大メンバー数 |

## GitHub Actions との連携

`package.xml` の日次自動生成 + メタデータ取得 + git コミットのパイプラインに組み込む場合の例:

```yaml
- name: Generate package.xml
  run: sf-package-xml -o ${{ secrets.SF_ORG_ALIAS }} --exclude-all-namespaces
```

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

## ライセンス

MIT
