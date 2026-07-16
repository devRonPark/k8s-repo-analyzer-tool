"""Command-line entry point (argparse; no heavyweight CLI framework)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .analyzer import analyze_repository
from .reporters.json_reporter import to_json, write_json
from .reporters.markdown_reporter import write_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-analyzer",
        description="Deterministic P0 Kubernetes-migration analyzer for source repositories.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="analyze a repository")
    analyze.add_argument("--repo", required=True, help="path to the repository to analyze")
    analyze.add_argument(
        "--profile", default="kubernetes-p0", help="analysis profile (default: kubernetes-p0)"
    )
    analyze.add_argument(
        "--build-system",
        default="auto",
        choices=["auto", "gradle", "maven"],
        help="which build system to analyze when several are present (default: auto)",
    )
    analyze.add_argument("--git-ref", default=None, help="optional commit/ref to record in metadata")
    analyze.add_argument("--json-output", default=None, help="path to write the JSON report")
    analyze.add_argument("--markdown-output", default=None, help="path to write the Markdown report")
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    try:
        result = analyze_repository(
            args.repo,
            profile=args.profile,
            git_ref=args.git_ref,
            build_system=args.build_system,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        write_json(result, args.json_output)
    if args.markdown_output:
        write_markdown(result, args.markdown_output)
    if not args.json_output and not args.markdown_output:
        sys.stdout.write(to_json(result))

    summary = (
        f"analyzed '{result.repository.name}': {len(result.components)} components, "
        f"{len(result.workload_mappings)} workloads, "
        f"{len(result.secrets)} secret candidates, "
        f"{len(result.unresolved_operational_inputs)} unresolved operational inputs"
    )
    print(summary, file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze":
        return _run_analyze(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
