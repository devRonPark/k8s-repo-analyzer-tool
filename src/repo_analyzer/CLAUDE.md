# src/repo_analyzer/

Core package. Data flows one-way: inventory → parsers → rules → models → reporters.

## Top-level modules

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `analyzer.py` | 130 | Orchestrator — all filesystem reads happen here, then calls the pure rule engine |
| `cli.py` | 66 | CLI entry point (`repo-analyzer analyze`), argparse |
| `inventory.py` | 135 | Discovers P0-relevant files by name/pattern (no content parsing); picks primary compose file |
| `models.py` | 126 | Pydantic v2 schema (`extra="forbid"`); field order fixes JSON key order for determinism |

## Sub-packages

| Directory | CLAUDE.md | Role |
|---|---|---|
| `parsers/` | [`parsers/CLAUDE.md`](parsers/CLAUDE.md) | One module per file format; each preserves source line ranges via `common.Located` |
| `reporters/` | [`reporters/CLAUDE.md`](reporters/CLAUDE.md) | JSON (canonical bytes) and Markdown (workload-centric) output |
| `rules/` | [`rules/CLAUDE.md`](rules/CLAUDE.md) | Pure functions: parsed facts in → `AnalysisResult` out; no I/O |
