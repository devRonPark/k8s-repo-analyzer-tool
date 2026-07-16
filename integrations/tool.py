"""Runtime-agnostic tool wrapper.

A single plain Python function that any agent runtime (OpenShell/Ollama, an
OpenAI-compatible function-calling loop, etc.) can call. It returns a JSON-safe
``dict`` and never raises for expected error conditions; failures are reported in
the structured payload so the agent can surface them instead of hallucinating.

The heavy lifting lives in ``repo_analyzer``. This wrapper only adapts types.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Make the analyzer importable whether or not the package is pip-installed.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from repo_analyzer.analyzer import analyze_repository as _analyze  # noqa: E402


def analyze_repository(
    repository_path: str,
    profile: str = "kubernetes-p0",
    git_ref: str | None = None,
    build_system: str = "auto",
) -> dict[str, Any]:
    """Analyze a repository and return a deterministic, JSON-safe result dict.

    ``build_system`` (``auto`` | ``gradle`` | ``maven``) forces which build system
    is analyzed when a repository ships more than one.

    On expected errors (missing path, unsupported profile/build system) a
    structured error object is returned instead of raising, so agents report the
    failure rather than falling back to generic Kubernetes advice.
    """

    try:
        result = _analyze(
            repository_path, profile=profile, git_ref=git_ref, build_system=build_system
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        return {
            "ok": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "profile": profile,
        }

    return {"ok": True, "profile": profile, "analysis": result.model_dump(mode="json")}


if __name__ == "__main__":  # pragma: no cover
    import json

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(analyze_repository(target), ensure_ascii=False, indent=2))
