"""Characterization tests for ``Package._build_package_section``."""

from __future__ import annotations

import pytest

from dblift.core.sql_model.package import Package

pytestmark = [pytest.mark.unit]


def test_existing_header_is_replaced_by_the_qualified_one() -> None:
    section = "CREATE OR REPLACE PACKAGE pkg AS\n  x NUMBER;\nEND;\n/"

    built = Package("PKG")._build_package_section(section, "HR.PKG", is_body=False)

    assert built == "CREATE OR REPLACE PACKAGE HR.PKG AS\nx NUMBER;\nEND;"


def test_headerless_body_gets_a_body_header() -> None:
    built = Package("PKG")._build_package_section("  x NUMBER;\nEND;", "HR.PKG", is_body=True)

    assert built == "CREATE OR REPLACE PACKAGE BODY HR.PKG\nx NUMBER;\nEND;"


def test_blank_section_builds_nothing() -> None:
    assert Package("PKG")._build_package_section("   ", "HR.PKG", is_body=True) == ""
