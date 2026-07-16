# src/repo_analyzer/reporters/

Output formatters. Receive an `AnalysisResult` model and serialize it.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `json_reporter.py` | 24 | Canonical JSON — deterministic bytes (intrinsic key order, stable indent, UTF-8) |
| `markdown_reporter.py` | — | Workload-centric Markdown report. Renders the Java/WAR component summary (language, build, artifact, application server, context path), plus the `runtime_dependencies` (§4b) and `container_image` (§8b) sections; splits §5 into ConfigMap candidates vs stack/build/profile facts. |
