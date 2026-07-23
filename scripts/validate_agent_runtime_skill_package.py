"""Validate runtime-neutral agent skill package structure."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_MANIFEST_FILE = "package.yaml"
REQUIRED_CANONICAL_FILES = (
    "canonical/workflow.md",
    "canonical/evidence-rules.md",
    "canonical/intake.md",
    "canonical/diagnosis-package-rubric.md",
    "canonical/validation.md",
)
REQUIRED_ADAPTER_FILES = (
    "adapters/codex/SKILL.md",
    "adapters/claude-code/COMMAND.md",
    "adapters/opencode/COMMAND.md",
)
REQUIRED_TERMS = (
    "Agent Runtime Skill Package",
    "Kubernetes Migration Field Assessment",
    "Evidence Result",
    "Migration Diagnosis Package",
    "Secret masking",
    "no-invention",
)
FORBIDDEN_CANONICAL_TERMS = (
    "Codex-only",
    "Claude Code-only",
    "OpenCode-only",
)


def validate_package(package_root: Path) -> list[str]:
    errors: list[str] = []
    if not package_root.is_dir():
        return [f"package root does not exist: {package_root}"]

    canonical_files, adapter_files, manifest_errors = _manifest_paths(package_root)
    errors.extend(manifest_errors)
    for expected in REQUIRED_CANONICAL_FILES:
        if expected not in canonical_files:
            errors.append(f"manifest does not list canonical file: {expected}")
    for expected in REQUIRED_ADAPTER_FILES:
        if expected not in adapter_files:
            errors.append(f"manifest does not list adapter file: {expected}")

    canonical_texts: list[str] = []
    for relative in canonical_files:
        path = package_root / relative
        if not path.is_file():
            errors.append(f"missing canonical file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        canonical_texts.append(text)
        for forbidden in FORBIDDEN_CANONICAL_TERMS:
            if forbidden in text:
                errors.append(f"{relative} contains runtime-specific term: {forbidden}")

    combined = "\n".join(canonical_texts)
    for term in REQUIRED_TERMS:
        if term not in combined:
            errors.append(f"canonical package does not define required term: {term}")

    for relative in adapter_files:
        path = package_root / relative
        if not path.is_file():
            errors.append(f"missing adapter file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        if "canonical/" not in text:
            errors.append(f"{relative} does not reference canonical/")
        if "Evidence Result" not in text:
            errors.append(f"{relative} does not preserve Evidence Result semantics")

    return errors


def _manifest_paths(package_root: Path) -> tuple[list[str], list[str], list[str]]:
    path = package_root / REQUIRED_MANIFEST_FILE
    if not path.is_file():
        return list(REQUIRED_CANONICAL_FILES), list(REQUIRED_ADAPTER_FILES), [
            f"missing manifest file: {REQUIRED_MANIFEST_FILE}"
        ]

    canonical: list[str] = []
    adapters: list[str] = []
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "canonical:":
            section = "canonical"
            continue
        if stripped == "adapters:":
            section = "adapters"
            continue
        if section == "canonical" and stripped.startswith("- "):
            canonical.append(stripped[2:].strip())
            continue
        if section == "adapters" and ":" in stripped:
            _, value = stripped.split(":", 1)
            adapters.append(value.strip())

    errors = []
    if not canonical:
        errors.append("manifest has no canonical file entries")
    if not adapters:
        errors.append("manifest has no adapter file entries")
    return canonical, adapters, errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    package_root = Path(args[0]) if args else Path("skills/kubernetes-field-assessment")
    errors = validate_package(package_root)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
