# tests/

All tests run fully offline — no network access.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | Package marker |
| `conftest.py` | 16 | Shared pytest fixtures (fixture paths, tmp dirs) |
| `test_parser_compose.py` | 52 | Compose YAML parser unit tests |
| `test_parser_dockerfile.py` | 41 | Dockerfile parser unit tests |
| `test_parser_dotenv.py` | 31 | `.env` parser unit tests |
| `test_parser_nginx.py` | 27 | Nginx config parser unit tests |
| `test_parser_python_settings.py` | 34 | Python BaseSettings AST parser unit tests |
| `test_golden_analysis.py` | 143 | Golden integration test — full pipeline against `fixtures/full-stack-fastapi/` |
| `test_determinism_and_errors.py` | 63 | Byte-level determinism, bad-profile, missing-file, repo-not-modified checks |

## Fixtures

`fixtures/full-stack-fastapi/` — pinned local copy of P0-relevant files from
`fastapi/full-stack-fastapi-template` @ `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`.
Never fetch from network; never modify this fixture without updating golden expectations.
