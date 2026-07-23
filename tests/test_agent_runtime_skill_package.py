import importlib.util
from pathlib import Path


def _load_validator():
    path = Path("scripts/validate_agent_runtime_skill_package.py")
    spec = importlib.util.spec_from_file_location(
        "validate_agent_runtime_skill_package", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_field_assessment_package_has_runtime_neutral_foundation() -> None:
    validator = _load_validator()

    errors = validator.validate_package(Path("skills/kubernetes-field-assessment"))

    assert errors == []


def test_validator_rejects_adapter_that_does_not_reference_canonical_package(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    package = tmp_path / "package"
    _write_manifest(package, validator.REQUIRED_CANONICAL_FILES, validator.REQUIRED_ADAPTER_FILES)
    for relative in validator.REQUIRED_CANONICAL_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Evidence Result\nMigration Diagnosis Package\n", encoding="utf-8")
    for relative in validator.REQUIRED_ADAPTER_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("standalone runtime instructions\n", encoding="utf-8")

    errors = validator.validate_package(package)

    assert any("does not reference canonical/" in error for error in errors)


def test_validator_rejects_manifest_that_does_not_list_required_adapter(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    package = tmp_path / "package"
    listed_adapters = validator.REQUIRED_ADAPTER_FILES[:-1]
    _write_manifest(package, validator.REQUIRED_CANONICAL_FILES, listed_adapters)
    for relative in validator.REQUIRED_CANONICAL_FILES:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "Agent Runtime Skill Package\n"
            "Kubernetes Migration Field Assessment\n"
            "Evidence Result\n"
            "Migration Diagnosis Package\n"
            "Secret masking\n"
            "no-invention\n",
            encoding="utf-8",
        )
    for relative in listed_adapters:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "See canonical/. Preserve Evidence Result semantics.\n",
            encoding="utf-8",
        )

    errors = validator.validate_package(package)

    assert any("manifest does not list adapter file" in error for error in errors)


def _write_manifest(
    package: Path,
    canonical_files: tuple[str, ...],
    adapter_files: tuple[str, ...],
) -> None:
    package.mkdir(parents=True, exist_ok=True)
    lines = ["canonical:"]
    lines.extend(f"  - {relative}" for relative in canonical_files)
    lines.append("adapters:")
    lines.extend(f"  adapter_{index}: {relative}" for index, relative in enumerate(adapter_files))
    (package / "package.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
