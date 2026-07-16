# src/repo_analyzer/reporters/

Output formatters. Receive an `AnalysisResult` model and serialize it.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `json_reporter.py` | 24 | Canonical JSON — deterministic bytes (sorted keys, stable indent, UTF-8) |
| `markdown_reporter.py` | 279 | Workload-centric Markdown report answering the 7 P0 questions |
