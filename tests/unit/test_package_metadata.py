"""The metadata PyPI shows: links, licence, author, topic and supported Python versions."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text("utf-8"))[
    "project"
]
SUPPORTED = ["3.11", "3.12", "3.13", "3.14"]


def test_project_urls_give_pypi_its_links():
    urls = PROJECT["urls"]
    assert urls["Homepage"] == "https://dblift.com"
    assert urls["Documentation"] == "https://docs.dblift.com/"
    assert urls["Source"] == "https://github.com/dblift/dblift"
    assert urls["Issues"] == "https://github.com/dblift/dblift/issues"
    assert urls["Changelog"] == "https://github.com/dblift/dblift/blob/main/CHANGELOG.md"


def test_licence_is_an_spdx_expression_without_the_superseded_classifier():
    assert PROJECT["license"] == "Apache-2.0"
    assert PROJECT["license-files"] == ["LICENSE"]
    assert not [c for c in PROJECT["classifiers"] if c.startswith("License ::")]


def test_authors_are_declared_without_a_personal_email():
    assert PROJECT["authors"] == [{"name": "DBLift"}]


def test_classifiers_cover_the_database_topic_and_every_supported_python():
    classifiers = set(PROJECT["classifiers"])
    assert "Topic :: Database" in classifiers
    assert {f"Programming Language :: Python :: {v}" for v in SUPPORTED} <= classifiers
    assert "Programming Language :: Python :: 3 :: Only" in classifiers
    assert "Programming Language :: Python :: Implementation :: CPython" in classifiers
    assert "Operating System :: OS Independent" in classifiers
    assert "Environment :: Console" in classifiers


def test_python_classifiers_match_requires_python():
    assert PROJECT["requires-python"] == ">=3.11"
    versions = {
        c.rsplit(" ", 1)[-1]
        for c in PROJECT["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    }
    assert sorted(versions, key=lambda v: int(v.split(".")[1])) == SUPPORTED
