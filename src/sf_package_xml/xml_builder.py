"""
package.xml 生成・分割ロジック
"""

import os
from xml.dom import minidom
import xml.etree.ElementTree as ET


# Salesforce Metadata API の1回の retrieve で指定できるファイル数の上限
SALESFORCE_RETRIEVE_LIMIT = 10_000


def split_metadata_map(
    metadata_map: dict[str, list[str]],
    max_members: int,
) -> list[dict[str, list[str]]]:
    """
    metadata_map をメンバー総数が max_members 以下になるように分割する。

    分割の方針:
      - タイプ単位でまとめて次のチャンクに詰める (タイプを途中で分断しない)
      - ただし 1 タイプのメンバー数が max_members を超える場合は、
        そのタイプだけで 1 チャンクとして切り出す (取得できる範囲で対応)

    Returns:
        分割後の metadata_map リスト。分割不要なら要素数 1 のリストを返す。
    """
    total = sum(len(v) for v in metadata_map.values())
    if total <= max_members:
        return [metadata_map]

    chunks: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    current_count = 0

    for xml_name, members in sorted(metadata_map.items()):
        count = len(members)

        if current_count + count > max_members and current:
            # 現在のチャンクが上限を超えるので確定して新チャンクへ
            chunks.append(current)
            current = {}
            current_count = 0

        current[xml_name] = members
        current_count += count

    if current:
        chunks.append(current)

    return chunks


def split_output_paths(output_path: str, num_chunks: int) -> list[str]:
    """
    出力ファイルパスを分割数に合わせてナンバリングしたパスのリストを返す。

    例: "package.xml", 3 → ["package_01.xml", "package_02.xml", "package_03.xml"]
    """
    base, ext = os.path.splitext(output_path)
    width = len(str(num_chunks))
    return [f"{base}_{str(i + 1).zfill(width)}{ext}" for i in range(num_chunks)]


def build_package_xml(metadata_map: dict[str, list[str]], api_version: str) -> str:
    """
    metadata_map から整形済み package.xml 文字列を生成して返す。

    Args:
        metadata_map: タイプ名 → メンバー名リスト の辞書。
                      メンバーが ["*"] の場合はワイルドカードとして出力される。
        api_version : Metadata API バージョン文字列 (例: "62.0")

    Returns:
        UTF-8 宣言付きの整形済み XML 文字列。
        タイプ名・メンバー名はともにアルファベット昇順にソートされる。
    """
    root = ET.Element("Package")
    root.set("xmlns", "http://soap.sforce.com/2006/04/metadata")

    for xml_name in sorted(metadata_map):
        members = sorted(set(metadata_map[xml_name]))
        if not members:
            continue

        types_elem = ET.SubElement(root, "types")
        for member in members:
            m_elem = ET.SubElement(types_elem, "members")
            m_elem.text = member
        n_elem = ET.SubElement(types_elem, "name")
        n_elem.text = xml_name

    ver_elem = ET.SubElement(root, "version")
    ver_elem.text = api_version

    # minidom で整形 (インデント4スペース)
    raw = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(raw)
    pretty = dom.toprettyxml(indent="    ", encoding="UTF-8").decode("utf-8")

    # toprettyxml が挿入する余分な空行を除去
    lines = [ln for ln in pretty.splitlines() if ln.strip()]
    return "\n".join(lines) + "\n"
