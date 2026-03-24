"""
Salesforce CLI ラッパーおよびメタデータ取得ロジック
"""

import json
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from sf_package_xml.filters import filter_namespaced


# スレッド間で標準出力が混在しないようにするロック
_print_lock = threading.Lock()


def tprint(*args, **kwargs) -> None:
    """スレッドセーフな print。複数スレッドからの出力が行単位で混在しないようにする。"""
    with _print_lock:
        print(*args, **kwargs)


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
    print("  stdValueSetRegistry.json を取得中 ...", flush=True)
    try:
        with urllib.request.urlopen(_STD_VALUE_SET_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        members = data.get("fullnames", [])
        if not members:
            raise ValueError("fullnames キーが空")
        print(f"  -> {len(members)} 件取得", flush=True)
        return members
    except Exception as e:
        print(f"[ERROR] stdValueSetRegistry.json の取得に失敗しました: {e}", file=sys.stderr)
        print(f"  取得先: {_STD_VALUE_SET_URL}", file=sys.stderr)
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
            tprint(f"  [ERROR] JSON 解析失敗: {' '.join(cmd)}", file=sys.stderr)
            if result.stderr:
                tprint(f"  stderr: {result.stderr[:200]}", file=sys.stderr)
            return None

        # スロットルエラーを検出してリトライ
        msg = data.get("message") or data.get("name") or ""
        if any(kw in msg for kw in _THROTTLE_KEYWORDS):
            wait = 2 ** (attempt + 1)  # 2s → 4s → 8s
            tprint(
                f"  [RETRY] スロットル検出 ({msg[:60]}), "
                f"{wait}s 後にリトライ ({attempt + 1}/{max_retries}): {' '.join(args[:3])}",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue

        # status != 0 でも result が返る場合 (警告付き成功) があるため警告のみに留める
        if data.get("status") not in (0, None) and "result" not in data:
            tprint(f"  [WARN] {msg or 'Unknown error'}", file=sys.stderr)

        return data

    tprint(f"  [ERROR] {max_retries} 回リトライ後も失敗: {' '.join(args[:3])}", file=sys.stderr)
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
    version = data.get("result", {}).get("instanceApiVersion")
    if isinstance(version, str) and version:
        return version
    return None


def get_api_usage(target_org: Optional[str]) -> Optional[tuple[int, int]]:
    """
    DailyApiRequests の使用数と上限を (used, max) のタプルで返す。

    "sf limits api display" を実行して DailyApiRequests エントリを探す。
    取得できない場合は None を返す (致命的エラーとは扱わない)。
    """
    data = run_sf(["limits", "api", "display"], target_org)
    if data is None:
        return None
    result = data.get("result") or []
    if not isinstance(result, list):
        return None
    for entry in result:
        if entry.get("name") == "DailyApiRequests":
            maximum = entry.get("max", 0)
            remaining = entry.get("remaining", 0)
            used = maximum - remaining
            return used, maximum
    return None


def print_api_usage(label: str, target_org: Optional[str]) -> Optional[tuple[int, int]]:
    """
    API コール数を取得して表示し、(used, max) タプルを返す。
    取得失敗時は警告のみ表示して None を返す。
    """
    usage = get_api_usage(target_org)
    if usage is None:
        print("  [WARN] API コール数の取得に失敗しました。", file=sys.stderr)
        return None
    used, maximum = usage
    pct = used / maximum * 100 if maximum else 0
    print(f"  {label}: {used:,} / {maximum:,}  ({pct:.1f}%)")
    return usage


def get_metadata_types(target_org: Optional[str]) -> list[dict]:
    """
    対象 org に存在するすべてのメタデータタイプ定義を返す。

    "sf org list metadata-types" を実行し、metadataObjects 配列を取得する。
    各要素は xmlName / inFolder / suffix 等のプロパティを持つ dict。
    """
    print("メタデータタイプ一覧を取得中 ...", flush=True)
    data = run_sf(["org", "list", "metadata-types"], target_org)
    if data is None:
        print("[ERROR] メタデータタイプの取得に失敗しました。", file=sys.stderr)
        return []

    # SF CLI のバージョンによって result の構造が異なる場合があるため両方を試みる
    objects = (
        data.get("result", {}).get("metadataObjects")
        or data.get("result", [])
    )
    if not isinstance(objects, list):
        print("[ERROR] メタデータタイプの取得に失敗しました。", file=sys.stderr)
        return []

    print(f"  取得済みタイプ数: {len(objects)}")
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
        print(f"  フォルダ一覧を取得中 ({folder_type}) ...", flush=True)
        folders = list_metadata(folder_type, target_org)
        if folders is None:
            print(f"  [ERROR] {folder_type} のフォルダ一覧取得に失敗しました。", file=sys.stderr)
            folders = []
        result[xml_name] = folders
        print(f"    -> {len(folders)} フォルダ")
    return result


# ---------------------------------------------------------------------------
# 並列処理用 worker
# ---------------------------------------------------------------------------

@dataclass
class TypeResult:
    """
    1タイプ分の取得結果をまとめるデータクラス。

    entries       : metadata_map に追加するエントリ (タイプ名 → メンバーリスト)。
                    フォルダ型の場合は folder_type と content_type の2エントリになる。
    excluded      : 名前空間除外で除いたメンバー数。
    skipped       : メンバーが0件のためスキップしたタイプ名 (該当なければ空文字)。
    verbose_lines : --verbose 表示用の行リスト。
    is_folder     : フォルダ型タイプの結果かどうか。進捗表示の分岐に使用する。
    error         : True = API 呼び出し失敗 (正常な 0件 とは区別する)
    """
    entries: dict[str, list[str]] = field(default_factory=dict)
    excluded: int = 0
    skipped: str = ""
    verbose_lines: list[str] = field(default_factory=list)
    is_folder: bool = False
    error: bool = False


def _process_explicit(
    xml_name: str,
    target_org: Optional[str],
    exclude_prefixes: tuple[str, ...],
    exclude_all_ns: bool,
    verbose: bool,
) -> TypeResult:
    """通常タイプ1件のメンバーを取得して TypeResult を返す。並列実行される。"""
    result = TypeResult()
    members = list_metadata(xml_name, target_org)
    if members is None:
        result.error = True
        result.skipped = xml_name
        if verbose:
            result.verbose_lines = [f">> {xml_name} [ERROR] メンバー取得失敗"]
        return result
    if not members:
        result.skipped = xml_name
        if verbose:
            result.verbose_lines = [f">> {xml_name} のメンバーを取得しました (0件)"]
        return result

    filtered = filter_namespaced(members, exclude_prefixes, exclude_all_ns)
    result.excluded = len(members) - len(filtered)
    if filtered:
        result.entries[xml_name] = filtered
    else:
        result.skipped = xml_name
    if verbose:
        result.verbose_lines = (
            [f">> {xml_name} のメンバーを取得しました ({len(filtered)}件)"]
            + [f"    {m}" for m in filtered]
        )
    return result


def _process_folder(
    xml_name: str,
    folder_type: str,
    folder_members: list[str],
    target_org: Optional[str],
    exclude_prefixes: tuple[str, ...],
    exclude_all_ns: bool,
    verbose: bool,
    on_folder_done: Callable[[str, int], None],
) -> TypeResult:
    """
    フォルダ型タイプ1件のコンテンツを取得して TypeResult を返す。並列実行される。

    フォルダ一覧 (folder_members) は呼び出し前に事前取得済みのものを受け取る。
    各フォルダのコンテンツ取得が完了するたびに on_folder_done(folder_name, count) を
    呼び出すことで、フォルダ単位の進捗をメインスレッドに通知する。
    """
    tprint(f"[FolderBased] {xml_name} ({len(folder_members)} フォルダ) 取得開始", flush=True)
    result = TypeResult(is_folder=True)

    if not folder_members:
        result.skipped = xml_name
        return result

    # フォルダ一覧をフィルタリングして entries に追加
    filtered_folders = filter_namespaced(folder_members, exclude_prefixes, exclude_all_ns)
    result.excluded += len(folder_members) - len(filtered_folders)
    result.entries[folder_type] = filtered_folders
    if verbose:
        for m in filtered_folders:
            tprint(f"    [{folder_type}] {m}", flush=True)

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
        if verbose:
            with _print_lock:
                print(f">> [{xml_name}] {folder_name} のメンバーを取得しました ({len(filtered)}件)")
                for m in filtered:
                    print(f"    {m}")
        on_folder_done(folder_name, len(filtered))

    if content_members:
        result.entries[xml_name] = content_members

    return result
