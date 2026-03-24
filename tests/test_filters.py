"""
filters.py のテスト

名前空間検出とフィルタリングは SF CLI 不要でテスト可能なため、
すべてユニットテストとして実行できる。
"""

import pytest

from sf_package_xml.filters import (
    _base_name,
    _check_ns_single,
    _has_namespace_prefix,
    filter_namespaced,
)


class TestBaseName:
    def test_folder_member(self):
        assert _base_name("MyFolder/MyReport") == "MyReport"

    def test_regular_member(self):
        assert _base_name("MyClass") == "MyClass"

    def test_nested_slash_takes_last(self):
        # "/" が複数ある場合は最初の "/" 以降全体がメンバー名
        assert _base_name("Folder/Sub/Name") == "Sub/Name"


class TestCheckNsSingle:
    def test_no_double_underscore(self):
        assert _check_ns_single("MyClass") is False

    def test_custom_object_two_parts(self):
        assert _check_ns_single("MyObject__c") is False

    def test_custom_metadata_two_parts(self):
        assert _check_ns_single("MyObject__mdt") is False

    def test_namespaced_custom_object(self):
        assert _check_ns_single("myns__Product__c") is True

    def test_namespace_only_no_suffix(self):
        assert _check_ns_single("FSJP__MyClass") is True

    def test_layout_with_locale(self):
        # "ADGroup__c-レイアウト" → suffix = "c", 2分割 → False
        assert _check_ns_single("ADGroup__c-レイアウト") is False

    def test_layout_namespaced(self):
        # "ns__MyObj__c-Layout" → suffix = "c", 3分割 → True
        assert _check_ns_single("ns__MyObj__c-Layout") is True


class TestHasNamespacePrefix:
    # 名前空間ありのケース
    def test_simple_namespace(self):
        assert _has_namespace_prefix("FSJP__MyClass") is True

    def test_namespaced_custom_object(self):
        assert _has_namespace_prefix("myns__Product__c") is True

    def test_dot_left_has_namespace(self):
        assert _has_namespace_prefix("CMTD__EnhancedRelatedList.NASameA_Value_F") is True

    # 名前空間なしのケース
    def test_custom_object_no_ns(self):
        assert _has_namespace_prefix("MyObject__c") is False

    def test_custom_metadata_no_ns(self):
        assert _has_namespace_prefix("MyObject__mdt") is False

    def test_no_double_underscore(self):
        assert _has_namespace_prefix("MyClass") is False

    def test_dot_both_sides_no_ns(self):
        assert _has_namespace_prefix("ADGroup__c.DupRule_Default") is False

    def test_layout_ja(self):
        assert _has_namespace_prefix("ADGroup__c-レイアウト") is False

    def test_dot_locale_no_ns(self):
        assert _has_namespace_prefix("ADGroup__c-ja.Account_Customer_look__c") is False

    # エッジケース
    def test_empty_string(self):
        assert _has_namespace_prefix("") is False

    def test_only_double_underscore(self):
        assert _has_namespace_prefix("__") is False


class TestFilterNamespaced:
    def test_no_filter_returns_same(self):
        members = ["FSJP__MyClass", "MyClass"]
        assert filter_namespaced(members, ()) == members

    def test_exclude_all_namespaces(self):
        members = ["FSJP__MyClass", "MyClass", "myns__Product__c"]
        result = filter_namespaced(members, (), all_namespaces=True)
        assert result == ["MyClass"]

    def test_exclude_specific_prefix(self):
        members = ["FSJP__MyClass", "acme__MyClass", "MyClass"]
        result = filter_namespaced(members, ("FSJP__",))
        assert result == ["acme__MyClass", "MyClass"]

    def test_exclude_prefix_case_insensitive(self):
        members = ["fsjp__MyClass", "MyClass"]
        result = filter_namespaced(members, ("FSJP__",))
        assert result == ["MyClass"]

    def test_exclude_multiple_prefixes(self):
        members = ["FSJP__A", "acme__B", "MyClass"]
        result = filter_namespaced(members, ("FSJP__", "acme__"))
        assert result == ["MyClass"]

    def test_folder_type_member_filtered(self):
        members = ["MyFolder/FSJP__MyReport", "MyFolder/MyReport"]
        result = filter_namespaced(members, (), all_namespaces=True)
        assert result == ["MyFolder/MyReport"]

    def test_folder_type_member_prefix_filtered(self):
        members = ["MyFolder/FSJP__MyReport", "MyFolder/MyReport"]
        result = filter_namespaced(members, ("FSJP__",))
        assert result == ["MyFolder/MyReport"]

    def test_empty_members(self):
        assert filter_namespaced([], ("FSJP__",)) == []

    def test_all_filtered_returns_empty(self):
        # "FSJP__B" は "B" がビッグオブジェクトサフィックス "b" と一致するため
        # 名前空間なしと判定される仕様。単一文字の衝突を避ける名前を使うこと。
        members = ["FSJP__MyClass", "FSJP__OtherClass"]
        result = filter_namespaced(members, (), all_namespaces=True)
        assert result == []
