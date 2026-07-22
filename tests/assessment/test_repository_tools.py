from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from repository_assessment.contracts import RunLimits
from repository_assessment.repository import (
    LocalRepositoryTools,
    RepositoryAccessError,
    RepositoryLimitError,
    UnsupportedFormatError,
)


def test_scan_is_metadata_only_and_selected_reads_are_cached(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts":{"start":"node app.js"}}\n', encoding="utf-8"
    )
    tools = LocalRepositoryTools(tmp_path, RunLimits())

    scan = tools.scan()
    first = tools.parse_structured("package.json", 1, 20)
    second = tools.parse_structured("package.json", 1, 20)

    assert [item.path for item in scan.entries] == ["package.json"]
    assert scan.revision_source == "tree_digest"
    assert first.content == {"scripts": {"start": "node app.js"}}
    assert second.content == first.content
    assert second.cached is True
    assert tools.usage.physical_reads == 1
    assert first.evidence[0].file == "package.json"
    assert first.evidence[0].digest == "sha256:" + hashlib.sha256(
        (tmp_path / "package.json").read_bytes()
    ).hexdigest()


def test_search_is_bounded_sorted_and_line_backed(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("listen(9000)\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("skip\nlisten(8080)\n", encoding="utf-8")
    tools = LocalRepositoryTools(tmp_path, RunLimits(matches_per_search=1))

    result = tools.search_text("listen(", ["."], regex=False)

    assert result.truncated is True
    assert [(item.file, item.line) for item in result.content] == [("a.txt", 2)]
    assert result.evidence[0].excerpt == "listen(8080)"


def test_structured_parsers_support_v1_formats(tmp_path: Path) -> None:
    files = {
        "value.yaml": "server:\n  port: 8080\n",
        "value.toml": '[server]\nport = 8080\n',
        "value.xml": '<server port="8080" />\n',
        "value.properties": "server.port=8080\n",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    tools = LocalRepositoryTools(tmp_path, RunLimits())

    assert tools.parse_structured("value.yaml", 1, 20).content == {
        "server": {"port": 8080}
    }
    assert tools.parse_structured("value.toml", 1, 20).content == {
        "server": {"port": 8080}
    }
    assert tools.parse_structured("value.xml", 1, 20).content == {
        "tag": "server",
        "attributes": {"port": "8080"},
        "text": "",
        "children": [],
    }
    assert tools.parse_structured("value.properties", 1, 20).content == {
        "server.port": "8080"
    }


def test_unknown_structured_extension_is_narrowly_unsupported(tmp_path: Path) -> None:
    (tmp_path / "settings.conf").write_text("port=8080\n", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError, match="settings.conf"):
        LocalRepositoryTools(tmp_path, RunLimits()).parse_structured(
            "settings.conf", 1, 20
        )


def test_read_and_search_limits_are_enforced(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    tools = LocalRepositoryTools(
        tmp_path,
        RunLimits(lines_per_read=2, search_calls=1, matches_per_search=5),
    )

    with pytest.raises(RepositoryLimitError, match="lines_per_read"):
        tools.read_lines("app.txt", 1, 3)
    tools.search_text("one", ["."])
    with pytest.raises(RepositoryLimitError, match="search_calls"):
        tools.search_text("two", ["."])


def test_list_find_context_and_tree_limit_are_deterministic(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("guide\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    tools = LocalRepositoryTools(tmp_path, RunLimits(tree_entries=10))

    listed = tools.list_tree("docs")
    found = tools.find_files(["**/*.py", "**/*.md"])
    limited = LocalRepositoryTools(tmp_path, RunLimits(tree_entries=1)).scan()

    assert [entry.path for entry in listed.content] == ["docs", "docs/README.md"]
    assert found.content == ["docs/README.md", "src/app.py"]
    assert listed.content[1].source_context == "documentation"
    assert limited.truncated is True
    assert len(limited.entries) == 1


def test_requested_revision_is_preserved_without_git_lookup(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_text("app\n", encoding="utf-8")

    scan = LocalRepositoryTools(tmp_path, RunLimits(), revision="release-2026").scan()

    assert scan.resolved_revision == "release-2026"
    assert scan.revision_source == "requested"


def test_invalid_regular_expression_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_text("app\n", encoding="utf-8")

    with pytest.raises(RepositoryAccessError, match="regular expression"):
        LocalRepositoryTools(tmp_path, RunLimits()).search_text("[", ["."], regex=True)
