"""
metadata.py のテスト

SF CLI への呼び出しは unittest.mock でモックし、外部依存なしでテストする。
"""

from unittest.mock import patch

from sf_package_xml.metadata import get_org_api_version


class TestGetOrgApiVersion:
    def test_returns_version_from_api_version_field(self):
        response = {"status": 0, "result": {"apiVersion": "66.0"}}
        with patch("sf_package_xml.metadata.run_sf", return_value=response):
            assert get_org_api_version(None) == "66.0"

    def test_returns_version_from_instance_api_version_field(self):
        response = {"status": 0, "result": {"instanceApiVersion": "63.0"}}
        with patch("sf_package_xml.metadata.run_sf", return_value=response):
            assert get_org_api_version(None) == "63.0"

    def test_api_version_takes_precedence_over_instance_api_version(self):
        response = {"status": 0, "result": {"apiVersion": "66.0", "instanceApiVersion": "63.0"}}
        with patch("sf_package_xml.metadata.run_sf", return_value=response):
            assert get_org_api_version(None) == "66.0"

    def test_returns_version_with_target_org(self):
        response = {"status": 0, "result": {"apiVersion": "62.0"}}
        with patch("sf_package_xml.metadata.run_sf", return_value=response):
            assert get_org_api_version("myOrg") == "62.0"

    def test_returns_none_when_run_sf_fails(self):
        with patch("sf_package_xml.metadata.run_sf", return_value=None):
            assert get_org_api_version(None) is None

    def test_returns_none_when_result_missing(self):
        with patch("sf_package_xml.metadata.run_sf", return_value={"status": 0, "result": {}}):
            assert get_org_api_version(None) is None

    def test_returns_none_when_version_empty_string(self):
        response = {"status": 0, "result": {"apiVersion": ""}}
        with patch("sf_package_xml.metadata.run_sf", return_value=response):
            assert get_org_api_version(None) is None

    def test_returns_none_when_version_is_not_string(self):
        response = {"status": 0, "result": {"apiVersion": 66}}
        with patch("sf_package_xml.metadata.run_sf", return_value=response):
            assert get_org_api_version(None) is None
