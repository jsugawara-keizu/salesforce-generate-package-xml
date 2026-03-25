"""
_filter_type_map() のユニットテスト
"""

from sf_package_xml.cli import _filter_type_map


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
        assert list(result.keys()) == ["ApexClass"]

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
