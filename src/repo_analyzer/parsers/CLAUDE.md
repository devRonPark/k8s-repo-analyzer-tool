# src/repo_analyzer/parsers/

One parser per file format. Every parser preserves source line ranges using
`common.Located` so evidence can trace back to exact lines.

## Files

| File | Lines | Format | Parser strategy |
|---|---|---|---|
| `__init__.py` | 0 | — | Package marker |
| `common.py` | 31 | — | `Located` wrapper, shared types for line-range tracking |
| `compose.py` | 239 | Docker Compose YAML | `ruamel.yaml` with line-preserving round-trip loader |
| `dockerfile.py` | 108 | Dockerfile | Instruction-level parser; joins `\` continuation lines |
| `dotenv.py` | 65 | `.env` | dotenv format key=value parser |
| `nginx.py` | 101 | nginx.conf | Brace/`;` tokenizer, directive-centric |
| `python_settings.py` | 82 | Python (Pydantic BaseSettings) | AST visitor → `BaseSettings` field extraction |

## Invariants

- Never hardcode line numbers — locate by structural node, report real range.
- Unsupported syntax → `ParseIssue` (warning or unsupported_construct), never silent.
- No I/O beyond the file content passed in.
