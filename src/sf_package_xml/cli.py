"""
CLI エントリーポイント
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from sf_package_xml.filters import filter_namespaced
from sf_package_xml.metadata import (
    FOLDER_BASED_TYPES,
    SKIP_TYPES,
    TypeResult,
    _print_lock,
    _process_explicit,
    _process_folder,
    fetch_standard_value_set_members,
    get_metadata_types,
    prefetch_folder_lists,
    print_api_usage,
    tprint,
)
from sf_package_xml.xml_builder import (
    SALESFORCE_RETRIEVE_LIMIT,
    build_package_xml,
    split_metadata_map,
    split_output_paths,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Salesforce org のすべてのメタデータを対象とする package.xml を生成します。"
    )
    parser.add_argument(
        "-o", "--target-org",
        help="対象 org のエイリアスまたはユーザー名 (省略時はデフォルト org)",
    )
    parser.add_argument(
        "-v", "--api-version",
        default="62.0",
        help="Metadata API バージョン (デフォルト: 62.0)",
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
        help="取得したメンバー名を1件ずつ標準出力に表示する。",
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
    args = parser.parse_args()

    target_org: Optional[str] = args.target_org
    api_version: str = args.api_version
    wildcard: bool = args.wildcard
    skip_folders: bool = args.skip_folders
    verbose: bool = args.verbose
    exclude_all_ns: bool = args.exclude_all_namespaces
    workers: int = args.workers

    # --exclude-namespace の引数を "NS__" 形式に正規化してタプルに変換
    exclude_prefixes: tuple[str, ...] = tuple(
        f"{ns}__" for ns in args.exclude_namespace
    )

    # ① 開始時刻を記録し、API コール数の使用状況を表示
    start_time = time.monotonic()
    print("API コール数を確認中 ...", flush=True)
    usage_before = print_api_usage("開始時", target_org)

    # ② 対象 org のメタデータタイプ一覧を取得
    all_types = get_metadata_types(target_org)
    if not all_types:
        sys.exit(1)

    type_map: dict[str, dict] = {t["xmlName"]: t for t in all_types if t.get("xmlName")}

    metadata_map: dict[str, list[str]] = {}
    skipped: list[str] = []
    error_types: list[str] = []
    excluded_count: int = 0

    # ③ StandardValueSet を先に取得 (GitHub への HTTP 呼び出し、逐次)
    if "StandardValueSet" in type_map:
        print("[StandardValueSet] メンバーを取得中 ...", flush=True)
        svs_members = fetch_standard_value_set_members()
        svs_filtered = filter_namespaced(svs_members, exclude_prefixes, exclude_all_ns)
        excluded_count += len(svs_members) - len(svs_filtered)
        metadata_map["StandardValueSet"] = svs_filtered
        if verbose:
            tprint("\n".join(f"    {m}" for m in svs_filtered), flush=True)

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
            if verbose:
                tprint(f"[Wildcard] {xml_name}: *", flush=True)

    else:
        # ⑤ 並列取得モード: タイプを explicit / folder の2グループに分けて並列実行

        explicit_types: list[str] = []
        folder_types: list[tuple[str, str]] = []

        for xml_name, mt in sorted(type_map.items()):
            if xml_name in SKIP_TYPES or xml_name == "StandardValueSet":
                continue
            in_folder: bool = mt.get("inFolder", False)
            if in_folder or xml_name in FOLDER_BASED_TYPES:
                if skip_folders:
                    tprint(f"[FolderBased] {xml_name} をスキップ (--skip-folders)", flush=True)
                    skipped.append(xml_name)
                else:
                    ft = FOLDER_BASED_TYPES.get(xml_name, f"{xml_name}Folder")
                    folder_types.append((xml_name, ft))
            elif mt.get("suffix") == "settings":
                # Settings 系タイプ (AccountSettings, CaseSettings 等) は
                # "sf org list metadata" が空を返すが * で取得可能なため、
                # API 呼び出しなしで直接 * をセットする。
                metadata_map[xml_name] = ["*"]
                if verbose:
                    tprint(f">> {xml_name} のメンバーを取得しました (Settings タイプのため *)", flush=True)
            else:
                explicit_types.append(xml_name)

        total_explicit = len(explicit_types)
        completed_explicit = 0

        # フォルダ一覧を事前取得して合計フォルダ数を確定する
        prefetched: dict[str, list[str]] = {}
        if folder_types:
            print("\nフォルダ一覧を事前取得中 ...", flush=True)
            prefetched = prefetch_folder_lists(folder_types, target_org)
        total_folder_items = sum(len(v) for v in prefetched.values())
        completed_folder_items = 0

        total_tasks = total_explicit + total_folder_items

        def _progress_line(label: str, label_count: int) -> str:
            """現在の進捗を1行で返す。ロック内から呼ぶこと。"""
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
            with _print_lock:
                completed_folder_items += 1
                print(_progress_line(f"[フォルダ] {folder_name}", count), flush=True)

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
            if verbose and result.verbose_lines:
                tprint("\n".join(result.verbose_lines), flush=True)
            if not result.is_folder:
                type_name = result.skipped or next(iter(result.entries), "")
                count = len(result.entries.get(type_name, []))
                with _print_lock:
                    completed_explicit += 1
                    print(_progress_line(f"[通常] {type_name}", count), flush=True)

        print(flush=True)
        print("=" * 60, flush=True)
        print(
            f"  メタデータ取得開始"
            f"  通常 {total_explicit} タイプ + フォルダ型 {len(folder_types)} タイプ"
            f" (フォルダ {total_folder_items} 件)"
            f"  {workers} ワーカー",
            flush=True,
        )
        print("=" * 60, flush=True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures: list = []

            # フォルダ型を先に submit する (処理時間が長いため早期に開始する)
            for xml_name, folder_type in folder_types:
                f = executor.submit(
                    _process_folder,
                    xml_name, folder_type, prefetched.get(xml_name, []),
                    target_org, exclude_prefixes, exclude_all_ns, verbose,
                    _on_folder_done,
                )
                futures.append(f)

            for xml_name in explicit_types:
                f = executor.submit(
                    _process_explicit,
                    xml_name, target_org, exclude_prefixes, exclude_all_ns, verbose,
                )
                futures.append(f)

            for future in as_completed(futures):
                _on_complete(future.result())

    # ⑥ メンバー総数を集計し、上限を超える場合は分割する
    total_members = sum(len(v) for v in metadata_map.values())
    max_members: int = args.max_members
    chunks = split_metadata_map(metadata_map, max_members)

    output_path: str = args.output
    if len(chunks) == 1:
        output_paths = [output_path]
    else:
        output_paths = split_output_paths(output_path, len(chunks))
        print(f"\n[INFO] メンバー総数 {total_members} 件が上限 {max_members} を超えるため "
              f"{len(chunks)} ファイルに分割します。", flush=True)

    # ⑦ 各チャンクを package.xml として書き出し
    print("\npackage.xml を生成中 ...", flush=True)
    for i, (chunk, path) in enumerate(zip(chunks, output_paths), 1):
        xml_content = build_package_xml(chunk, api_version)
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_content)
        chunk_total = sum(len(v) for v in chunk.values())
        print(f"  [{i}/{len(chunks)}] {path}  ({len(chunk)} タイプ / {chunk_total} メンバー)")

    # 完了サマリ
    total_elapsed = time.monotonic() - start_time
    print(flush=True)
    print("=" * 60, flush=True)
    print(f"  完了  ({total_elapsed:.1f}s)")
    print("=" * 60, flush=True)
    print(f"  メタデータタイプ数 : {len(metadata_map)}")
    print(f"  メンバー総数       : {total_members}")
    print(f"  出力ファイル数     : {len(chunks)}")
    if excluded_count:
        ns_label = "すべての名前空間" if exclude_all_ns else ", ".join(args.exclude_namespace)
        print(f"  名前空間除外件数  : {excluded_count} ({ns_label})")

    print(f"\n取得済みメタデータタイプ ({len(metadata_map)}件):")
    for name in sorted(metadata_map):
        count = len(metadata_map[name])
        print(f"  {name} ({count}件)")

    if skipped:
        print(f"\nスキップ / メンバー0件 ({len(skipped)}件):")
        for name in sorted(skipped):
            print(f"  {name}")

    if error_types:
        print(f"\n[ERROR] 取得失敗タイプ ({len(error_types)}件):", file=sys.stderr)
        for name in sorted(error_types):
            print(f"  {name}", file=sys.stderr)

    print("\nAPI コール数を確認中 ...", flush=True)
    usage_after = print_api_usage("終了時", target_org)
    if usage_before and usage_after:
        consumed = usage_after[0] - usage_before[0]
        print(f"  今回の消費数     : {consumed:,}")

    # 終了コード
    #   0: 完全成功
    #   1: 致命的エラー (org 接続失敗等) ← 既存の sys.exit(1)
    #   2: 部分失敗 (一部タイプの取得失敗、package.xml は生成済み)
    if error_types:
        sys.exit(2)
