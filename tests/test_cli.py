"""
cli ヘルパー関数のユニットテスト
"""

from sf_package_xml.cli import _build_summary, _filter_type_map, _resolve_output_path


class TestFilterTypeMap:
    def setup_method(self):
        self.type_map = {
            "ApexClass": {"xmlName": "ApexClass"},
            "CustomObject": {"xmlName": "CustomObject"},
            "Report": {"xmlName": "Report", "inFolder": True},
            "Workflow": {"xmlName": "Workflow"},
        }

    def test_no_filter_returns_original(self):
        result = _filter_type_map(self.type_map, [], [])
        assert result is self.type_map

    def test_include_types(self):
        result = _filter_type_map(self.type_map, ["ApexClass", "Workflow"], [])
        assert set(result.keys()) == {"ApexClass", "Workflow"}

    def test_include_single_type(self):
        result = _filter_type_map(self.type_map, ["ApexClass"], [])
        assert set(result.keys()) == {"ApexClass"}

    def test_include_nonexistent_type(self):
        result = _filter_type_map(self.type_map, ["NonExistent"], [])
        assert result == {}

    def test_exclude_types(self):
        result = _filter_type_map(self.type_map, [], ["Report"])
        assert "Report" not in result
        assert set(result.keys()) == {"ApexClass", "CustomObject", "Workflow"}

    def test_exclude_multiple_types(self):
        result = _filter_type_map(self.type_map, [], ["Report", "Workflow"])
        assert set(result.keys()) == {"ApexClass", "CustomObject"}

    def test_include_then_exclude(self):
        # include で絞り込んだ後に exclude を適用
        result = _filter_type_map(
            self.type_map,
            ["ApexClass", "Workflow", "Report"],
            ["Report"],
        )
        assert set(result.keys()) == {"ApexClass", "Workflow"}

    def test_exclude_nonexistent_type(self):
        # 存在しないタイプを除外しても変わらない
        result = _filter_type_map(self.type_map, [], ["NonExistent"])
        assert result == self.type_map

    def test_does_not_mutate_original(self):
        original_keys = set(self.type_map.keys())
        _filter_type_map(self.type_map, ["ApexClass"], ["Workflow"])
        assert set(self.type_map.keys()) == original_keys


class TestResolveOutputPath:
    def test_no_output_dir(self):
        assert _resolve_output_path("package.xml", None) == "package.xml"

    def test_output_dir_with_filename(self):
        assert _resolve_output_path("package.xml", "manifest") == "manifest/package.xml"

    def test_output_dir_overrides_dirname(self):
        # --output に path が含まれていても --output-dir で上書きされる
        assert _resolve_output_path("out/pkg.xml", "manifest") == "manifest/pkg.xml"

    def test_output_dir_trailing_slash(self):
        assert _resolve_output_path("package.xml", "manifest/") == "manifest/package.xml"


class TestBuildSummary:
    def setup_method(self):
        self.metadata_map = {
            "ApexClass": ["ClassA", "ClassB", "ClassC"],
            "CustomObject": ["Obj__c"],
            "Workflow": [],
        }

    def test_total_types(self):
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        assert result["total_types"] == 3

    def test_total_members(self):
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        assert result["total_members"] == 4

    def test_api_version(self):
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        assert result["api_version"] == "62.0"

    def test_target_org(self):
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        assert result["target_org"] == "myOrg"

    def test_target_org_default_when_none(self):
        result = _build_summary("62.0", None, self.metadata_map, ["package.xml"])
        assert result["target_org"] == "default"

    def test_output_files(self):
        paths = ["package_1.xml", "package_2.xml"]
        result = _build_summary("62.0", "myOrg", self.metadata_map, paths)
        assert result["output_files"] == paths

    def test_types_member_counts(self):
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        assert result["types"]["ApexClass"] == 3
        assert result["types"]["CustomObject"] == 1
        assert result["types"]["Workflow"] == 0

    def test_types_sorted(self):
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        assert list(result["types"].keys()) == sorted(result["types"].keys())

    def test_generated_at_is_iso8601(self):
        from datetime import datetime
        result = _build_summary("62.0", "myOrg", self.metadata_map, ["package.xml"])
        # ISO 8601 形式でパースできることを確認
        dt = datetime.fromisoformat(result["generated_at"])
        assert dt.tzinfo is not None  # タイムゾーン付き
