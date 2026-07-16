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
| `test_parser_maven.py` | — | Maven `pom.xml` parser unit tests (packaging, java version+line, dep scope, profiles, `${prop}` left verbatim) |
| `test_parser_webxml.py` | — | Servlet `web.xml` parser unit tests |
| `test_parser_spring_xml.py` | — | Spring datasource detector (embedded/external/CDI-negative) |
| `test_golden_analysis.py` | 143 | Golden integration — full pipeline against `fixtures/full-stack-fastapi/` |
| `test_golden_jpetstore.py` | — | Golden integration (Maven WAR) — structured assertions against `fixtures/jpetstore-6/` |
| `test_java_generalization.py` | — | Category regression: implicit Dockerfile, published-port fallback, Maven-without-compose, empty-repo guard, jpetstore not modified |
| `test_determinism_and_errors.py` | 63 | Byte-level determinism, bad-profile, missing-file, repo-not-modified checks |

## Fixtures

`fixtures/full-stack-fastapi/` — pinned local copy of P0-relevant files from
`fastapi/full-stack-fastapi-template` @ `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`.

`fixtures/jpetstore-6/` — pinned local copy of P0-relevant files from
`mybatis/jpetstore-6` @ `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d` (Maven WAR on
an external servlet container). `mvnw`/`mvnw.cmd` are minimal placeholders — only
their presence drives build-tool detection; the analyzer never reads them.

Never fetch from network; never modify a fixture without updating golden expectations.
