from __future__ import annotations

from pathlib import Path

import pytest

from repository_assessment.contracts import RunLimits
from repository_assessment.repository import (
    LocalRepositoryTools,
    RepositoryAccessError,
    RepositoryLimitError,
)


def test_repository_tools_reject_traversal_and_escaping_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("TOP_SECRET=visible", encoding="utf-8")
    (repository / "escape").symlink_to(outside)
    tools = LocalRepositoryTools(repository, RunLimits())

    with pytest.raises(RepositoryAccessError, match="outside repository"):
        tools.read_lines("../outside-secret.txt", 1, 1)
    with pytest.raises(RepositoryAccessError, match="outside repository"):
        tools.read_lines("escape", 1, 1)


def test_secret_values_are_masked_before_text_or_structured_observation(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "DATABASE_PASSWORD=hunter2\nPORT=8080\n", encoding="utf-8"
    )
    (tmp_path / "settings.json").write_text(
        '{"api_key":"abcd", "port":8080}\n', encoding="utf-8"
    )
    tools = LocalRepositoryTools(tmp_path, RunLimits())

    text = tools.read_lines(".env", 1, 2)
    structured = tools.parse_structured("settings.json", 1, 20)

    assert "hunter2" not in text.content
    assert "DATABASE_PASSWORD=[REDACTED]" in text.content
    assert "PORT=8080" in text.content
    assert text.evidence[0].masked is True
    assert structured.content == {"api_key": "[REDACTED]", "port": 8080}
    assert "abcd" not in structured.model_dump_json()


def test_binary_and_oversized_files_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"hello\x00world")
    (tmp_path / "large.txt").write_text("x" * 17, encoding="utf-8")
    tools = LocalRepositoryTools(tmp_path, RunLimits(single_file_bytes=16))

    with pytest.raises(RepositoryAccessError, match="binary"):
        tools.read_lines("binary.bin", 1, 1)
    with pytest.raises(RepositoryLimitError, match="single_file_bytes"):
        tools.read_lines("large.txt", 1, 1)


def test_generated_vendor_and_cache_paths_are_excluded(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    for directory in ("node_modules", "target", ".git"):
        path = tmp_path / directory
        path.mkdir()
        (path / "hidden.txt").write_text("hidden\n", encoding="utf-8")

    scan = LocalRepositoryTools(tmp_path, RunLimits()).scan()

    assert [entry.path for entry in scan.entries] == ["src", "src/app.py"]


def test_repository_is_not_modified_by_reads(tmp_path: Path) -> None:
    source = tmp_path / "app.txt"
    source.write_text("listen=8080\n", encoding="utf-8")
    before = source.read_bytes()
    tools = LocalRepositoryTools(tmp_path, RunLimits())

    tools.scan()
    tools.read_lines("app.txt", 1, 1)
    tools.search_text("listen", ["."])
    tools.file_info("app.txt")

    assert source.read_bytes() == before
