"""
名前空間フィルタリング

Salesforce メンバー名から名前空間プレフィックスを検出し、除外するロジック。
"""

import re


# Salesforce の標準カスタムサフィックス一覧 (小文字で比較)
_CUSTOM_SUFFIXES = frozenset([
    "c",            # カスタムオブジェクト / カスタム項目
    "e",            # プラットフォームイベント
    "b",            # ビッグオブジェクト
    "x",            # 外部オブジェクト
    "mdt",          # カスタムメタデータタイプ
    "kav",          # ナレッジ記事バージョン
    "ka",           # ナレッジ記事
    "share",        # 共有オブジェクト
    "feed",         # フィードオブジェクト
    "history",      # 項目履歴オブジェクト
    "tag",          # タグオブジェクト
    "changeevent",  # 変更データキャプチャイベント
])

# 名前空間プレフィックス部分の正規表現: 英数字およびアンダースコア 1〜15文字、先頭は英字
# Salesforce 公式仕様: "can contain only underscores and alphanumeric characters,
# and must begin with a letter"
_NS_PART_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,14}$")


def _base_name(member: str) -> str:
    """
    フォルダ型メンバー名 "FolderName/MemberName" からメンバー名部分のみを返す。
    "/" を含まない通常のメンバー名はそのまま返す。
    """
    return member.split("/", 1)[-1]


def _check_ns_single(name: str) -> bool:
    """
    区切り文字 ("." / "-") を含まない単一トークンに対して名前空間プレフィックスを判定する。

    判定ロジック:
      "__" で分割し、末尾パーツが既知カスタムサフィックスかどうかで場合分けする。

      (A) 末尾がカスタムサフィックス (例: "c", "mdt") の場合:
          - 分割数 == 2  →  "MyObject__c"     → 名前空間なし (False)
          - 分割数 >= 3  →  "ns__MyObject__c" → 名前空間あり (True)

      (B) 末尾がカスタムサフィックスでない場合:
          - 先頭パーツが名前空間規則に合致するか確認
          - 合致すれば名前空間あり (True)、しなければ False

    "-" 処理:
      Layout の "ObjectName__c-LayoutName" 形式など、末尾パーツに "-" が入る場合は
      "-" より前の部分のみをサフィックスとして扱う。
    """
    parts = name.split("__")
    if len(parts) < 2:
        return False

    last = parts[-1].split("-")[0].lower()
    if last in _CUSTOM_SUFFIXES:
        return len(parts) > 2

    return bool(_NS_PART_PATTERN.match(parts[0]))


def _has_namespace_prefix(name: str) -> bool:
    """
    メンバー名が Salesforce 名前空間プレフィックスを持つか判定する。

    メタデータタイプによってメンバー名に "." が含まれる場合がある:
      - "ObjectName.MemberName" 形式:
          DuplicateRule / QuickAction / WorkflowAlert / CustomMetadata 等
          例: "ADGroup__c.DupRule_Default"
              "CMTD__EnhancedRelatedList.NASameA_IndicatorValue_F"

      "." の左右どちらかに名前空間プレフィックスがあれば全体を名前空間ありと判定する。
      これにより以下を正しく区別できる:
        "ADGroup__c.DupRule_Default"              → 左 False / 右 False → False
        "CMTD__EnhancedRelatedList.NASameA_..."   → 左 True            → True

    例:
      "FSJP__MyClass"                               → True  (B: 先頭 FSJP が名前空間)
      "myns__Product__c"                            → True  (A: 3分割、末尾 c はサフィックス)
      "MyObject__c"                                 → False (A: 2分割)
      "MyObject__mdt"                               → False (A: 2分割)
      "MyClass"                                     → False (__なし)
      "ADGroup__c.DupRule_Default"                  → False (左右とも False)
      "ADGroup__c-レイアウト"                       → False (A: suffix = "c", 2分割)
      "ADGroup__c-ja.Account_Customer_look__c"      → False (左右とも False)
      "CMTD__EnhancedRelatedList.NASameA_Value_F"   → True  (左が True)
    """
    if "." in name:
        left, right = name.rsplit(".", 1)
        return _check_ns_single(left) or _check_ns_single(right)
    return _check_ns_single(name)


def filter_namespaced(
    members: list[str],
    prefixes: tuple[str, ...],
    all_namespaces: bool = False,
) -> list[str]:
    """
    名前空間プレフィックスを持つメンバーをリストから除外して返す。

    Args:
        members       : フィルタリング対象のメンバー名リスト
        prefixes      : 除外する名前空間プレフィックス ("NS__" 形式)。
                        大文字小文字を区別しない。
        all_namespaces: True の場合、名前空間プレフィックスを持つ
                        すべてのメンバーを除外する。

    Returns:
        フィルタリング後のメンバー名リスト。
        prefixes が空かつ all_namespaces が False の場合は members をそのまま返す。
    """
    if not prefixes and not all_namespaces:
        return members

    result = []
    for m in members:
        # フォルダ型 "Folder/Member" はメンバー名部分で判定
        name = _base_name(m)

        # --exclude-all-namespaces: 名前空間プレフィックス検出ロジックで判定
        if all_namespaces and _has_namespace_prefix(name):
            continue

        # --exclude-namespace: 指定プレフィックスで前方一致 (大文字小文字を無視)
        if prefixes and name.lower().startswith(tuple(p.lower() for p in prefixes)):
            continue

        result.append(m)
    return result
