from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.reporters.json_reporter import to_json
from repo_analyzer.reporters.markdown_reporter import to_markdown


def test_json_is_byte_identical_across_runs(golden_repo):
    first = to_json(analyze_repository(str(golden_repo)))
    second = to_json(analyze_repository(str(golden_repo)))
    assert first == second


def test_markdown_is_stable_across_runs(golden_repo):
    first = to_markdown(analyze_repository(str(golden_repo)))
    second = to_markdown(analyze_repository(str(golden_repo)))
    assert first == second


def _dir_digest(root: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        sha.update(path.relative_to(root).as_posix().encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


def test_analysis_does_not_modify_target_repo(golden_repo, tmp_path):
    copy = tmp_path / "repo"
    shutil.copytree(golden_repo, copy)
    before = _dir_digest(copy)
    analyze_repository(str(copy))
    assert _dir_digest(copy) == before


def test_missing_repo_raises():
    with pytest.raises(FileNotFoundError):
        analyze_repository("/no/such/repo/anywhere")


def test_unsupported_profile_raises(golden_repo):
    with pytest.raises(ValueError):
        analyze_repository(str(golden_repo), profile="kubernetes-p9")


def test_empty_repo_reports_no_compose(tmp_path):
    result = analyze_repository(str(tmp_path))
    assert result.components == []
    assert any(w.code == "no_compose" for w in result.warnings)
    # Even with nothing to analyze, operational unknowns are reported honestly.
    assert result.unresolved_operational_inputs


def test_malformed_compose_recorded_not_crashed(tmp_path):
    (tmp_path / "compose.yml").write_text("services: [unclosed\n")
    result = analyze_repository(str(tmp_path))
    assert any(u.construct_type == "yaml_parse_error" for u in result.unsupported_constructs)
