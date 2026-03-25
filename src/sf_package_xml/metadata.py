"""
Salesforce CLI ラッパーおよびメタデータ取得ロジック
"""

import json
import logging
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from sf_package_xml.filters import filter_namespaced

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StandardValueSet メンバー取得
# ---------------------------------------------------------------------------

# stdValueSetRegistry.json の取得先
#
# 出典: Salesforce CLI コアライブラリ (forcedotcom/source-deploy-retrieve)
#   リポジトリ: https://github.com/forcedotcom/source-deploy-retrieve
#   ファイル  : src/registry/stdValueSetRegistry.json
#
# このファイルが必要な理由:
#   StandardValueSet は "sf org list metadata -m StandardValueSet" が空を返す仕様のため、
#   メンバーを動的に列挙できない。SF CLI 自身もこの JSON を静的にバンドルして参照している。
#
# 注意: Salesforce は年3回リリース (Spring / Summer / Winter) があり、
#   新しい StandardValueSet が追加されることがある。
#   このスクリプトは毎回 GitHub から最新版を取得するため常に最新状態を反映する。
_STD_VALUE_SET_URL = (
    "https://raw.githubusercontent.com/forcedotcom/source-deploy-retrieve"
    "/main/src/registry/stdValueSetRegistry.json"
)


def fetch_standard_value_set_members() -> list[str]:
    """
    stdValueSetRegistry.json を GitHub から取得し、fullnames リストを返す。

    取得失敗 (ネットワークエラー / JSON 不正 / fullnames が空) の場合は
    エラーメッセージを出力してスクリプトを終了する。
    """
    logger.info("stdValueSetRegistry.json を取得中 ...")
    try:
        with urllib.request.urlopen(_STD_VALUE_SET_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        members = data.get("fullnames", [])
        if not members:
            raise ValueError("fullnames キーが空")
        logger.info("StandardValueSet: %d 件取得", len(members))
        return members
    except Exception as e:
        logger.error("stdValueSetRegistry.json の取得に失敗しました: %s", e)
        logger.error("取得先: %s", _STD_VALUE_SET_URL)
        sys.exit(1)


# ---------------------------------------------------------------------------
# フォルダ型メタデータの定義
# ---------------------------------------------------------------------------

# フォルダ型コンテンツ型 → フォルダ型 のマッピング
#
# Metadata API では Report / Dashboard / Document / EmailTemplate は
# "フォルダ型" として扱われ、直接 <members>*</members> では取得できない。
# 取得手順:
#   1. フォルダ型 (例: ReportFolder) で全フォルダ名を取得
#   2. 各フォルダに対して sf org list metadata -m Report --folder <name> を実行
#   3. package.xml には "FolderName/MemberName" 形式で記載
FOLDER_BASED_TYPES: dict[str, str] = {
    "Report": "ReportFolder",
    "Dashboard": "DashboardFolder",
    "Document": "DocumentFolder",
    "EmailTemplate": "EmailFolder",
}

# sf org list metadata-types の結果に含まれるが、package.xml には直接記載しないタイプ。
# フォルダ型のフォルダ自体 (ReportFolder 等) は FOLDER_BASED_TYPES の処理の中で
# metadata_map に追加するため、ここで事前除外しておく。
SKIP_TYPES = set(FOLDER_BASED_TYPES.values())


# ---------------------------------------------------------------------------
# SF CLI ラッパー
# ---------------------------------------------------------------------------

def run_sf(
    args: list[str],
    target_org: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    SF CLI コマンドを --json オプション付きで実行し、結果を dict で返す。

    スロットルエラー ("SERVER_UNAVAILABLE" / "EXCEEDED_ID_LIMIT" / "REQUEST_LIMIT_EXCEEDED")
    を検出した場合は exponential backoff でリトライする (最大 max_retries 回)。

    JSON のパースに失敗した場合、または全リトライが失敗した場合は
    エラーを stderr に出力して None を返す。
    呼び出し元は None チェックでエラーを検出できる。
    """
    _THROTTLE_KEYWORDS = ("SERVER_UNAVAILABLE", "EXCEEDED_ID_LIMIT", "REQUEST_LIMIT_EXCEEDED")

    cmd = ["sf"] + args + ["--json"]
    if target_org:
        cmd += ["-o", target_org]

    for attempt in range(max_retries):
        result = subprocess.run(cmd, capture_output=True, text=True)

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("JSON 解析失敗: %s", " ".join(cmd))
            if result.stderr:
                logger.error("stderr: %s", result.stderr[:200])
            return None

        # スロットルエラーを検出してリトライ
        msg = data.get("message") or data.get("name") or ""
        if any(kw in msg for kw in _THROTTLE_KEYWORDS):
            wait = 2 ** (attempt + 1)  # 2s → 4s → 8s
            logger.warning(
                "スロットル検出 (%s), %ds 後にリトライ (%d/%d): %s",
                msg[:60], wait, attempt + 1, max_retries, " ".join(args[:3]),
            )
            time.sleep(wait)
            continue

        # status != 0 でも result が返る場合 (警告付き成功) があるため警告のみに留める
        if data.get("status") not in (0, None) and "result" not in data:
            logger.warning("%s", msg or "Unknown error")

        return data

    logger.error("%d 回リトライ後も失敗: %s", max_retries, " ".join(args[:3]))
    return None


def get_org_api_version(target_org: Optional[str]) -> Optional[str]:
    """
    org の instanceApiVersion を取得して返す。

    "sf org display" を実行し、result.instanceApiVersion フィールドを返す。
    取得できない場合は None を返す (呼び出し元でフォールバックすること)。
    """
    data = run_sf(["org", "display"], target_org)
    if data is None:
        return None
    result = data.get("result", {})
    version = result.get("apiVersion") or result.get("instanceApiVersion")
    if isinstance(version, str) and version:
        return version
    return None


def _fetch_limits(target_org: Optional[str]) -> Optional[list]:
    """sf limits api display を実行し、limits リストを返す。失敗時は None。"""
    data = run_sf(["limits", "api", "display"], target_org)
    if data is None:
        return None
    result = data.get("result") or []
    return result if isinstance(result, list) else None


def _extract_usage(limits: list, name: str) -> Optional[tuple[int, int]]:
    """limits リストから指定名のエントリを探して (used, max) を返す。"""
    for entry in limits:
        if entry.get("name") == name:
            maximum = entry.get("max", 0)
            remaining = entry.get("remaining", 0)
            return maximum - remaining, maximum
    return None


# 表示対象の API 制限: (limit_name, 表示名) の順で表示する
# DailyMetadataApiRequests は org エディションによって存在しない場合がある。
# 存在しない limit は print_api_usage が自動的に非表示にする。
_TRACKED_LIMITS = [
    ("DailyApiRequests", "REST API"),
    ("DailyMetadataApiRequests", "Metadata API"),
]


def get_api_usage(target_org: Optional[str]) -> Optional[tuple[int, int]]:
    """
    DailyApiRequests の使用数と上限を (used, max) のタプルで返す。

    "sf limits api display" を実行して DailyApiRequests エントリを探す。
    取得できない場合は None を返す (致命的エラーとは扱わない)。
    """
    limits = _fetch_limits(target_org)
    if limits is None:
        return None
    return _extract_usage(limits, "DailyApiRequests")


def print_api_usage(label: str, target_org: Optional[str]) -> dict[str, tuple[int, int]]:
    """
    REST API / Metadata API のコール数を取得して表示する。

    {limit_name: (used, max)} の辞書を返す。
    取得失敗時は警告のみ表示して空辞書を返す。
    """
    limits = _fetch_limits(target_org)
    if limits is None:
        logger.warning("API コール数の取得に失敗しました。")
        return {}
    result: dict[str, tuple[int, int]] = {}
    for limit_name, display_name in _TRACKED_LIMITS:
        usage = _extract_usage(limits, limit_name)
        if usage is not None:
            used, maximum = usage
            pct = used / maximum * 100 if maximum else 0
            logger.info("%s [%s]: %s / %s  (%.1f%%)",
                        label, display_name, f"{used:,}", f"{maximum:,}", pct)
            result[limit_name] = usage
    return result


def get_metadata_types(target_org: Optional[str]) -> list[dict]:
    """
    対象 org に存在するすべてのメタデータタイプ定義を返す。

    "sf org list metadata-types" を実行し、metadataObjects 配列を取得する。
    各要素は xmlName / inFolder / suffix 等のプロパティを持つ dict。
    """
    logger.info("メタデータタイプ一覧を取得中 ...")
    data = run_sf(["org", "list", "metadata-types"], target_org)
    if data is None:
        logger.error("メタデータタイプの取得に失敗しました。")
        return []

    # SF CLI のバージョンによって result の構造が異なる場合があるため両方を試みる
    objects = (
        data.get("result", {}).get("metadataObjects")
        or data.get("result", [])
    )
    if not isinstance(objects, list):
        logger.error("メタデータタイプの取得に失敗しました。")
        return []

    logger.info("取得済みタイプ数: %d", len(objects))
    return objects


def list_metadata(
    xml_name: str,
    target_org: Optional[str],
    folder: Optional[str] = None,
) -> Optional[list[str]]:
    """
    指定メタデータタイプの全メンバーの fullName リストを返す。

    folder を指定した場合はフォルダ型取得モードとなり、
    "sf org list metadata -m <type> --folder <folder>" を実行する。

    Returns:
        メンバーリスト。メンバーが存在しない場合は空リスト []。
        API 呼び出し失敗時は None (呼び出し元でエラー検出に使用)。
    """
    args = ["org", "list", "metadata", "-m", xml_name]
    if folder:
        args += ["--folder", folder]

    data = run_sf(args, target_org)
    if data is None:
        return None

    result = data.get("result") or []

    # 単一オブジェクトが返る場合 (list でない) は空扱い
    if not isinstance(result, list):
        return []

    return [m["fullName"] for m in result if m.get("fullName")]


def prefetch_folder_lists(
    folder_types: list[tuple[str, str]],
    target_org: Optional[str],
) -> dict[str, list[str]]:
    """
    フォルダ型タイプのフォルダ一覧を事前に取得して辞書で返す。

    並列取得を開始する前に呼び出すことで、各フォルダ型のフォルダ総数を確定し、
    進捗表示の分母として使用できるようにする。

    Args:
        folder_types : (content_type, folder_type) のリスト
        target_org   : 対象 org

    Returns:
        content_type → フォルダ名リスト の辞書
    """
    result: dict[str, list[str]] = {}
    for xml_name, folder_type in folder_types:
        logger.info("フォルダ一覧を取得中 (%s) ...", folder_type)
        folders = list_metadata(folder_type, target_org)
        if folders is None:
            logger.error("%s のフォルダ一覧取得に失敗しました。", folder_type)
            folders = []
        result[xml_name] = folders
        logger.info("  -> %d フォルダ", len(folders))
    return result


# ---------------------------------------------------------------------------
# 並列処理用 worker
# ---------------------------------------------------------------------------

@dataclass
class TypeResult:
    """
    1タイプ分の取得結果をまとめるデータクラス。

    entries   : metadata_map に追加するエントリ (タイプ名 → メンバーリスト)。
                フォルダ型の場合は folder_type と content_type の2エントリになる。
    excluded  : 名前空間除外で除いたメンバー数。
    skipped   : メンバーが0件のためスキップしたタイプ名 (該当なければ空文字)。
    is_folder : フォルダ型タイプの結果かどうか。進捗表示の分岐に使用する。
    error     : True = API 呼び出し失敗 (正常な 0件 とは区別する)
    """
    entries: dict[str, list[str]] = field(default_factory=dict)
    excluded: int = 0
    skipped: str = ""
    is_folder: bool = False
    error: bool = False


def _process_explicit(
    xml_name: str,
    target_org: Optional[str],
    exclude_prefixes: tuple[str, ...],
    exclude_all_ns: bool,
) -> TypeResult:
    """通常タイプ1件のメンバーを取得して TypeResult を返す。並列実行される。"""
    result = TypeResult()
    members = list_metadata(xml_name, target_org)
    if members is None:
        result.error = True
        result.skipped = xml_name
        logger.debug("[ERROR] %s のメンバー取得失敗", xml_name)
        return result
    if not members:
        result.skipped = xml_name
        logger.debug("%s: 0件", xml_name)
        return result

    filtered = filter_namespaced(members, exclude_prefixes, exclude_all_ns)
    result.excluded = len(members) - len(filtered)
    if filtered:
        result.entries[xml_name] = filtered
    else:
        result.skipped = xml_name
    logger.debug("%s: %d 件取得", xml_name, len(filtered))
    for m in filtered:
        logger.debug("    %s", m)
    return result


def _process_folder(
    xml_name: str,
    folder_type: str,
    folder_members: list[str],
    target_org: Optional[str],
    exclude_prefixes: tuple[str, ...],
    exclude_all_ns: bool,
    on_folder_done: Callable[[str, int], None],
) -> TypeResult:
    """
    フォルダ型タイプ1件のコンテンツを取得して TypeResult を返す。並列実行される。

    フォルダ一覧 (folder_members) は呼び出し前に事前取得済みのものを受け取る。
    各フォルダのコンテンツ取得が完了するたびに on_folder_done(folder_name, count) を
    呼び出すことで、フォルダ単位の進捗をメインスレッドに通知する。
    """
    logger.info("[FolderBased] %s (%d フォルダ) 取得開始", xml_name, len(folder_members))
    result = TypeResult(is_folder=True)

    if not folder_members:
        result.skipped = xml_name
        return result

    # フォルダ一覧をフィルタリングして entries に追加
    filtered_folders = filter_namespaced(folder_members, exclude_prefixes, exclude_all_ns)
    result.excluded += len(folder_members) - len(filtered_folders)
    result.entries[folder_type] = filtered_folders
    for m in filtered_folders:
        logger.debug("  [%s] %s", folder_type, m)

    # 各フォルダのコンテンツを逐次取得
    content_members: list[str] = []
    for folder_name in folder_members:
        members = list_metadata(xml_name, target_org, folder=folder_name)
        if members is None:
            result.error = True
            members = []
        filtered = filter_namespaced(members, exclude_prefixes, exclude_all_ns)
        result.excluded += len(members) - len(filtered)
        content_members.extend(filtered)
        logger.debug("[%s] %s: %d 件", xml_name, folder_name, len(filtered))
        for m in filtered:
            logger.debug("    %s", m)
        on_folder_done(folder_name, len(filtered))

    if content_members:
        result.entries[xml_name] = content_members

    return result
