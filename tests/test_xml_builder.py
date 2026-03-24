"""
xml_builder.py のテスト

XML 生成・分割ロジックは外部依存なしでテスト可能。
"""

import pytest

from sf_package_xml.xml_builder import (
    build_package_xml,
    split_metadata_map,
    split_output_paths,
)


class TestBuildPackageXml:
    def test_xml_declaration(self):
        result = build_package_xml({"ApexClass": ["MyClass"]}, "62.0")
        assert result.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_namespace_attr(self):
        result = build_package_xml({"ApexClass": ["MyClass"]}, "62.0")
        assert 'xmlns="http://soap.sforce.com/2006/04/metadata"' in result

    def test_member_and_name(self):
        result = build_package_xml({"ApexClass": ["MyClass"]}, "62.0")
        assert "<members>MyClass</members>" in result
        assert "<name>ApexClass</name>" in result

    def test_version(self):
        result = build_package_xml({"ApexClass": ["MyClass"]}, "62.0")
        assert "<version>62.0</version>" in result

    def test_members_sorted(self):
        result = build_package_xml({"ApexClass": ["ZClass", "AClass"]}, "62.0")
        assert result.index("AClass") < result.index("ZClass")

    def test_types_sorted(self):
        result = build_package_xml(
            {"Workflow": ["WFlow"], "ApexClass": ["AClass"]}, "62.0"
        )
        assert result.index("ApexClass") < result.index("Workflow")

    def test_wildcard_member(self):
        result = build_package_xml({"ApexClass": ["*"]}, "62.0")
        assert "<members>*</members>" in result

    def test_duplicate_members_deduped(self):
        result = build_package_xml({"ApexClass": ["MyClass", "MyClass"]}, "62.0")
        assert result.count("<members>MyClass</members>") == 1

    def test_empty_member_list_skipped(self):
        result = build_package_xml({"ApexClass": [], "CustomObject": ["MyObj__c"]}, "62.0")
        assert "ApexClass" not in result
        assert "MyObj__c" in result

    def test_ends_with_newline(self):
        result = build_package_xml({"ApexClass": ["MyClass"]}, "62.0")
        assert result.endswith("\n")

    def test_no_blank_lines(self):
        result = build_package_xml({"ApexClass": ["MyClass"]}, "62.0")
        for line in result.splitlines():
            assert line.strip() != "", f"空行が含まれています: {repr(line)}"


class TestSplitMetadataMap:
    def test_no_split_when_under_limit(self):
        metadata_map = {"ApexClass": ["A", "B", "C"]}
        chunks = split_metadata_map(metadata_map, 100)
        assert len(chunks) == 1
        assert chunks[0] == metadata_map

    def test_no_split_when_exactly_at_limit(self):
        metadata_map = {"ApexClass": ["A"] * 10}
        chunks = split_metadata_map(metadata_map, 10)
        assert len(chunks) == 1

    def test_split_into_two_chunks(self):
        metadata_map = {
            "ApexClass": ["A"] * 6,
            "CustomObject": ["B"] * 6,
        }
        chunks = split_metadata_map(metadata_map, 10)
        assert len(chunks) == 2

    def test_all_members_preserved_after_split(self):
        metadata_map = {
            "ApexClass": ["A"] * 6,
            "CustomObject": ["B"] * 6,
        }
        chunks = split_metadata_map(metadata_map, 10)
        total = sum(len(v) for c in chunks for v in c.values())
        assert total == 12

    def test_single_type_exceeding_limit_is_one_chunk(self):
        # タイプを途中で分断しない仕様
        metadata_map = {"ApexClass": ["A"] * 15}
        chunks = split_metadata_map(metadata_map, 10)
        assert len(chunks) == 1

    def test_three_chunks(self):
        metadata_map = {f"Type{i:02d}": ["X"] * 4 for i in range(9)}
        chunks = split_metadata_map(metadata_map, 10)
        # 4*9=36 members, max=10 → 4chunks (4+4+4+4 or similar)
        assert len(chunks) >= 3

    def test_empty_map(self):
        chunks = split_metadata_map({}, 10)
        assert len(chunks) == 1
        assert chunks[0] == {}


class TestSplitOutputPaths:
    def test_single_digit_no_padding(self):
        paths = split_output_paths("package.xml", 2)
        assert paths == ["package_1.xml", "package_2.xml"]

    def test_double_digit_padded(self):
        paths = split_output_paths("package.xml", 10)
        assert paths[0] == "package_01.xml"
        assert paths[9] == "package_10.xml"

    def test_count_matches_num_chunks(self):
        paths = split_output_paths("package.xml", 5)
        assert len(paths) == 5

    def test_nested_path(self):
        paths = split_output_paths("manifest/package.xml", 2)
        assert paths == ["manifest/package_1.xml", "manifest/package_2.xml"]

    def test_custom_extension(self):
        paths = split_output_paths("out/pkg.xml", 3)
        assert all(p.endswith(".xml") for p in paths)
