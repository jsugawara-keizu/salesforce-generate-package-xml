"""
CLI エントリーポイント
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from sf_package_xml import __version__
from sf_package_xml.filters import filter_namespaced
from sf_package_xml.metadata import (
    FOLDER_BASED_TYPES,
    SKIP_TYPES,
    TypeResult,
    _TRACKED_LIMITS,
    _process_explicit,
    _process_folder,
    fetch_standard_value_set_members,
    get_metadata_types,
    get_org_api_version,
    prefetch_folder_lists,
    print_api_usage,
)
from sf_package_xml.xml_builder import (
    SALESFORCE_RETRIEVE_LIMIT,
    build_package_xml,
    split_metadata_map,
    split_output_paths,
)

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool, log_file: Optional[str]) -> None:
    """
    ルートロガーを設定する。

    verbose=True のとき DEBUG レベル、それ以外は INFO レベル。
    log_file を指定するとファイルにも同時出力する。
    フォーマット: "YYYY-MM-DD HH:MM:SS LEVEL    メッセージ"
    """
    fmt = "%(asctime)s %(levelname)-8s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as e:
            print(f"[ERROR] ログファイルを開けませんでした: {log_file}: {e}", file=sys.stderr)
            sys.exit(1)
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt,
                        handlers=handlers, force=True)


def _resolve_output_path(output: str, output_dir: Optional[str]) -> str:
    """
    --output-dir が指定された場合、output のファイル名部分を output_dir に移動する。

    例:
        _resolve_output_path("package.xml", "manifest/")  -> "manifest/package.xml"
        _resolve_output_path("out/pkg.xml", "manifest/")  -> "manifest/pkg.xml"
        _resolve_output_path("package.xml", None)          -> "package.xml"
    """
    if output_dir:
        return os.path.join(output_dir, os.path.basename(output))
    return output


def _build_summary(
    api_version: str,
    target_org: Optional[str],
    metadata_map: dict[str, list[str]],
    output_paths: list[str],
) -> dict:
    """
    実行結果のサマリ辞書を構築する。--summary-json オプションで JSON ファイルに書き出す。

    フィールド:
        generated_at  : UTC 生成日時 (ISO 8601)
        api_version   : 使用した Metadata API バージョン
        target_org    : 対象 org (未指定時は "default")
        total_types   : 取得できたメタデータタイプ数
        total_members : 取得できたメンバー総数
        output_files  : 生成した package.xml のパスリスト
        types         : タイプ名 → メンバー数 の辞書 (ソート済み)
    """
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_version": api_version,
        "target_org": target_org or "default",
        "total_types": len(metadata_map),
        "total_members": sum(len(v) for v in metadata_map.values()),
        "output_files": output_paths,
        "types": {name: len(members) for name, members in sorted(metadata_map.items())},
    }


def _filter_type_map(
    type_map: dict[str, dict],
    include_types: list[str],
    exclude_types: list[str],
) -> dict[str, dict]:
    """
    --include-types / --exclude-types に基づいて type_map を絞り込む。

    - include_types が指定された場合: そのタイプのみを残す
    - exclude_types が指定された場合: そのタイプを除外する
    - 両方指定された場合: include で絞り込んだ後に exclude を適用する
    """
    result = type_map
    if include_types:
        include_set = set(include_types)
        result = {k: v for k, v in result.items() if k in include_set}
    if exclude_types:
        exclude_set = set(exclude_types)
        result = {k: v for k, v in result.items() if k not in exclude_set}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Salesforce org のすべてのメタデータを対象とする package.xml を生成します。"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sf-package-xml {__version__}",
    )
    parser.add_argument(
        "-o", "--target-org",
        help="対象 org のエイリアスまたはユーザー名 (省略時はデフォルト org)",
    )
    parser.add_argument(
        "-v", "--api-version",
        default=None,
        help="Metadata API バージョン (省略時は org から自動取得、取得失敗時は 62.0)",
    )
    parser.add_argument(
        "--output",
        default="package.xml",
        help="出力ファイルパス (デフォルト: package.xml)",
    )
    parser.add_argument(
        "--wildcard",
        action="store_true",
        help="全タイプを <members>*</members> で出力する高速モード。"
             "一部タイプ (StandardValueSet / フォルダ型) には適用されない。",
    )
    parser.add_argument(
        "--skip-folders",
        action="store_true",
        help="フォルダ型メタデータ (Report / Dashboard / Document / EmailTemplate) を除外する。"
             "レポート・ダッシュボードが多いテスト環境での高速化に使用する。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="取得したメンバー名を1件ずつ表示する (DEBUG ログレベルを有効にする)。",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        default=None,
        help="ログをファイルにも出力する。指定したパスに追記する。"
             "例: --log-file logs/run.log",
    )
    parser.add_argument(
        "--exclude-namespace",
        metavar="NS",
        nargs="+",
        default=[],
        help="除外する名前空間プレフィックスを指定する (複数指定可、大文字小文字を区別しない)。"
             "例: --exclude-namespace FSJP acme",
    )
    parser.add_argument(
        "--exclude-all-namespaces",
        action="store_true",
        help="名前空間プレフィックスを持つすべてのメンバーを除外する。"
             "管理パッケージのコンポーネントを一括除外したい場合に使用する。",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        metavar="N",
        help="並列実行するワーカー数 (デフォルト: 8)。"
             "増やすほど高速になるが org の API レート制限に注意。",
    )
    parser.add_argument(
        "--max-members",
        type=int,
        default=SALESFORCE_RETRIEVE_LIMIT,
        metavar="N",
        help=f"1ファイルあたりの最大メンバー数 (デフォルト: {SALESFORCE_RETRIEVE_LIMIT})。"
             "超過時は package_01.xml, package_02.xml ... に自動分割する。",
    )
    parser.add_argument(
        "--include-types",
        nargs="+",
        metavar="TYPE",
        default=[],
        help="取得対象とするメタデータタイプを指定する (複数指定可)。"
             "指定した場合はこれらのタイプのみを取得する。"
             "例: --include-types ApexClass CustomObject",
    )
    parser.add_argument(
        "--exclude-types",
        nargs="+",
        metavar="TYPE",
        default=[],
        help="除外するメタデータタイプを指定する (複数指定可)。"
             "--skip-folders の汎用版。"
             "例: --exclude-types Report Dashboard AnalyticsSnapshot",
    )
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="org のメタデータタイプ一覧を表示して終了する。package.xml は生成しない。",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="出力先ディレクトリを指定する。--output のファイル名はそのまま使用する。"
             "指定したディレクトリが存在しない場合は自動作成する。"
             "例: --output-dir manifest/",
    )
    parser.add_argument(
        "--summary-json",
        metavar="PATH",
        default=None,
        help="実行結果のサマリ (タイプ別メンバー数・生成日時等) を JSON ファイルに出力する。"
             "日次追跡で前回との差分比較に使用できる。"
             "例: --summary-json summary.json",
    )
    args = parser.parse_args()

    # ログ設定 (引数解析の直後に実行)
    _setup_logging(args.verbose, args.log_file)

    _FALLBACK_API_VERSION = "62.0"

    target_org: Optional[str] = args.target_org
    if args.api_version is not None:
        api_version: str = args.api_version
    else:
        detected = get_org_api_version(target_org)
        if detected:
            logger.info("API バージョンを org から自動取得しました: %s", detected)
            api_version = detected
        else:
            logger.warning(
                "API バージョンの自動取得に失敗しました。"
                "フォールバック値 %s を使用します。",
                _FALLBACK_API_VERSION,
            )
            api_version = _FALLBACK_API_VERSION
    wildcard: bool = args.wildcard
    skip_folders: bool = args.skip_folders
    exclude_all_ns: bool = args.exclude_all_namespaces
    workers: int = args.workers

    # --exclude-namespace の引数を "NS__" 形式に正規化してタプルに変換
    exclude_prefixes: tuple[str, ...] = tuple(
        f"{ns}__" for ns in args.exclude_namespace
    )

    # ① 開始時刻を記録し、API コール数の使用状況を表示
    start_time = time.monotonic()
    logger.info("API コール数を確認中 ...")
    usage_before = print_api_usage("開始時", target_org)

    # ② 対象 org のメタデータタイプ一覧を取得
    all_types = get_metadata_types(target_org)
    if not all_types:
        sys.exit(1)

    type_map: dict[str, dict] = {t["xmlName"]: t for t in all_types if t.get("xmlName")}

    # --list-types: タイプ一覧を表示して終了
    if args.list_types:
        logger.info("メタデータタイプ一覧 (%d 件):", len(type_map))
        for name in sorted(type_map.keys()):
            mt = type_map[name]
            markers = []
            if mt.get("inFolder") or name in FOLDER_BASED_TYPES:
                markers.append("フォルダ型")
            if mt.get("suffix") == "settings":
                markers.append("Settings")
            suffix = f"  [{', '.join(markers)}]" if markers else ""
            logger.info("  %s%s", name, suffix)
        sys.exit(0)

    # --include-types / --exclude-types でタイプを絞り込む
    if args.include_types or args.exclude_types:
        before = len(type_map)
        type_map = _filter_type_map(type_map, args.include_types, args.exclude_types)
        logger.info("タイプフィルタ適用: %d → %d タイプ", before, len(type_map))
        if not type_map:
            logger.error(
                "フィルタ適用後に対象タイプが0件になりました。"
                " --include-types / --exclude-types の指定を確認してください。"
            )
            sys.exit(1)

    metadata_map: dict[str, list[str]] = {}
    skipped: list[str] = []
    error_types: list[str] = []
    excluded_count: int = 0

    # ③ StandardValueSet を先に取得 (GitHub への HTTP 呼び出し、逐次)
    if "StandardValueSet" in type_map:
        logger.info("[StandardValueSet] メンバーを取得中 ...")
        svs_members = fetch_standard_value_set_members()
        svs_filtered = filter_namespaced(svs_members, exclude_prefixes, exclude_all_ns)
        excluded_count += len(svs_members) - len(svs_filtered)
        metadata_map["StandardValueSet"] = svs_filtered
        for m in svs_filtered:
            logger.debug("    %s", m)

    # ④ --wildcard モード: API 呼び出し不要、即座にマップを構築
    if wildcard:
        for xml_name, mt in type_map.items():
            if xml_name in SKIP_TYPES or xml_name == "StandardValueSet":
                continue
            in_folder = mt.get("inFolder", False)
            if skip_folders and (in_folder or xml_name in FOLDER_BASED_TYPES):
                skipped.append(xml_name)
                continue
            metadata_map.setdefault(xml_name, ["*"])
            logger.debug("[Wildcard] %s: *", xml_name)

    else:
        # ⑤ 並列取得モード: タイプを explicit / folder の2グループに分けて並列実行

        explicit_types: list[str] = []
        folder_types: list[tuple[str, str]] = []

        for xml_name, mt in sorted(type_map.items()):
            if xml_name in SKIP_TYPES or xml_name == "StandardValueSet":
                continue
            in_folder = mt.get("inFolder", False)
            if in_folder or xml_name in FOLDER_BASED_TYPES:
                if skip_folders:
                    logger.info("[FolderBased] %s をスキップ (--skip-folders)", xml_name)
                    skipped.append(xml_name)
                else:
                    ft = FOLDER_BASED_TYPES.get(xml_name, f"{xml_name}Folder")
                    folder_types.append((xml_name, ft))
            elif mt.get("suffix") == "settings":
                # Settings 系タイプ (AccountSettings, CaseSettings 等) は
                # "sf org list metadata" が空を返すが * で取得可能なため、
                # API 呼び出しなしで直接 * をセットする。
                metadata_map[xml_name] = ["*"]
                logger.debug("%s: * (Settings タイプ)", xml_name)
            else:
                explicit_types.append(xml_name)

        total_explicit = len(explicit_types)
        completed_explicit = 0

        # フォルダ一覧を事前取得して合計フォルダ数を確定する
        prefetched: dict[str, list[str]] = {}
        if folder_types:
            logger.info("フォルダ一覧を事前取得中 ...")
            prefetched = prefetch_folder_lists(folder_types, target_org)
        total_folder_items = sum(len(v) for v in prefetched.values())
        completed_folder_items = 0

        total_tasks = total_explicit + total_folder_items

        # _on_folder_done はワーカースレッドから呼ばれるため、カウンタ更新にロックを使う
        _lock = threading.Lock()

        def _progress_line(label: str, label_count: int) -> str:
            """現在の進捗を1行で返す。"""
            completed = completed_explicit + completed_folder_items
            pct = completed / total_tasks * 100 if total_tasks else 0
            elapsed = time.monotonic() - start_time
            if completed > 0:
                eta = elapsed / completed * (total_tasks - completed)
                eta_str = f", 残り約{eta:.0f}s"
            else:
                eta_str = ""
            return (
                f"  {label} ({label_count}件)"
                f" → {completed}/{total_tasks} ({pct:.1f}%, {elapsed:.1f}s{eta_str})"
            )

        def _on_folder_done(folder_name: str, count: int) -> None:
            """フォルダ1件のコンテンツ取得完了時に進捗を更新する。"""
            nonlocal completed_folder_items
            with _lock:
                completed_folder_items += 1
                logger.info(_progress_line(f"[フォルダ] {folder_name}", count))

        def _on_complete(result: TypeResult) -> None:
            """タイプ1件の取得完了時に metadata_map へ反映し、通常タイプの進捗を表示する。"""
            nonlocal excluded_count, completed_explicit
            for key, vals in result.entries.items():
                metadata_map.setdefault(key, []).extend(vals)
            excluded_count += result.excluded
            if result.error:
                error_types.append(result.skipped)
            elif result.skipped:
                skipped.append(result.skipped)
            if not result.is_folder:
                type_name = result.skipped or next(iter(result.entries), "")
                count = len(result.entries.get(type_name, []))
                with _lock:
                    completed_explicit += 1
                    logger.info(_progress_line(f"[通常] {type_name}", count))

        logger.info("")
        logger.info("=" * 60)
        logger.info(
            "  メタデータ取得開始"
            "  通常 %d タイプ + フォルダ型 %d タイプ (フォルダ %d 件)  %d ワーカー",
            total_explicit, len(folder_types), total_folder_items, workers,
        )
        logger.info("=" * 60)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures: list = []

            # フォルダ型を先に submit する (処理時間が長いため早期に開始する)
            for xml_name, folder_type in folder_types:
                f = executor.submit(
                    _process_folder,
                    xml_name, folder_type, prefetched.get(xml_name, []),
                    target_org, exclude_prefixes, exclude_all_ns,
                    _on_folder_done,
                )
                futures.append(f)

            for xml_name in explicit_types:
                f = executor.submit(
                    _process_explicit,
                    xml_name, target_org, exclude_prefixes, exclude_all_ns,
                )
                futures.append(f)

            for future in as_completed(futures):
                _on_complete(future.result())

    # ⑥ メンバー総数を集計し、上限を超える場合は分割する
    total_members = sum(len(v) for v in metadata_map.values())
    max_members: int = args.max_members
    chunks = split_metadata_map(metadata_map, max_members)

    output_path: str = _resolve_output_path(args.output, args.output_dir)
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
    if len(chunks) == 1:
        output_paths = [output_path]
    else:
        output_paths = split_output_paths(output_path, len(chunks))
        logger.info(
            "メンバー総数 %d 件が上限 %d を超えるため %d ファイルに分割します。",
            total_members, max_members, len(chunks),
        )

    # ⑦ 各チャンクを package.xml として書き出し
    logger.info("package.xml を生成中 ...")
    for i, (chunk, path) in enumerate(zip(chunks, output_paths), 1):
        xml_content = build_package_xml(chunk, api_version)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(xml_content)
        chunk_total = sum(len(v) for v in chunk.values())
        logger.info("  [%d/%d] %s  (%d タイプ / %d メンバー)",
                    i, len(chunks), path, len(chunk), chunk_total)

    # ⑧ --summary-json が指定された場合はサマリを JSON ファイルに書き出す
    if args.summary_json:
        summary = _build_summary(api_version, target_org, metadata_map, output_paths)
        summary_path = args.summary_json
        summary_dir = os.path.dirname(summary_path)
        if summary_dir:
            os.makedirs(summary_dir, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as fp:
            json.dump(summary, fp, ensure_ascii=False, indent=2)
        logger.info("サマリを出力しました: %s", summary_path)

    # 完了サマリ
    total_elapsed = time.monotonic() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info("  完了  (%.1fs)", total_elapsed)
    logger.info("=" * 60)
    logger.info("  メタデータタイプ数 : %d", len(metadata_map))
    logger.info("  メンバー総数       : %d", total_members)
    logger.info("  出力ファイル数     : %d", len(chunks))
    if excluded_count:
        ns_label = "すべての名前空間" if exclude_all_ns else ", ".join(args.exclude_namespace)
        logger.info("  名前空間除外件数  : %d (%s)", excluded_count, ns_label)

    logger.info("取得済みメタデータタイプ (%d件):", len(metadata_map))
    for name in sorted(metadata_map):
        count = len(metadata_map[name])
        logger.info("  %s (%d件)", name, count)

    if skipped:
        logger.info("スキップ / メンバー0件 (%d件):", len(skipped))
        for name in sorted(skipped):
            logger.info("  %s", name)

    if error_types:
        logger.error("取得失敗タイプ (%d件):", len(error_types))
        for name in sorted(error_types):
            logger.error("  %s", name)

    logger.info("API コール数を確認中 ...")
    usage_after = print_api_usage("終了時", target_org)
    if usage_before and usage_after:
        for limit_name, display_name in _TRACKED_LIMITS:
            if limit_name in usage_before and limit_name in usage_after:
                consumed = usage_after[limit_name][0] - usage_before[limit_name][0]
                logger.info("  今回の消費数 [%s]: %s", display_name, f"{consumed:,}")

    # 終了コード
    #   0: 完全成功
    #   1: 致命的エラー (org 接続失敗等) ← 既存の sys.exit(1)
    #   2: 部分失敗 (一部タイプの取得失敗、package.xml は生成済み)
    if error_types:
        sys.exit(2)
