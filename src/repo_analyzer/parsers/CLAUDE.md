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
| `xml_source.py` | — | XML (any) | Line-preserving SAX tree (`XmlNode`); prefixes kept in `qname`, stripped in `tag`; external entities disabled (offline/safe) |
| `maven.py` | — | Maven `pom.xml` | Structural via `xml_source`; packaging, finalName, java version (+line), deps w/ scope, `${prop}` resolution, profiles→cargo container ids |
| `webxml.py` | — | Servlet `web.xml` | Servlets, filters, listeners, servlet-mappings (url-patterns) |
| `spring_xml.py` | — | Spring context XML | Narrow datasource detector: embedded-database + init scripts vs external `DataSource` bean/JDBC URL; namespace-checks Spring vs CDI `<beans>` |
| `gradle.py` | — | `build.gradle`(`.kts`) | Line/brace block parser (Groovy+Kotlin): `plugins{}` (id+version+line), `dependencies{}` (configuration+coordinate), Java toolchain / sourceCompatibility, group/version, `-P` build properties (`hasProperty`/`findProperty`/`gradleProperty` → `build_properties`, deduped+sorted+located); companion `settings.gradle` (rootProject.name) + `gradle-wrapper.properties` (pinned version). Captures `alias(libs.…)` plugin refs and `libs.…` dependency refs; `apply_version_catalog(build, catalog)` resolves them to real coordinates/ids (unresolved → `ParseIssue`); other unrecognised declarations → `ParseIssue` |
| `version_catalog.py` | — | `gradle/libs.versions.toml` | stdlib `tomllib`; `[versions]`/`[libraries]`/`[plugins]`; resolves `libs.spring.starter.webflux` → module and `libs.plugins.spring.boot` → id (catalog key `-` ↔ accessor `.`), incl. `version.ref`; malformed TOML → `toml_parse_error` issue |
| `spring_properties.py` | — | `application*.properties` | key/value + line; profile from filename (`application-<p>.properties`); `${ENV:default}` placeholder extraction |
| `spring_yaml.py` | — | `application*.yml`/`.yaml` | `ruamel.yaml` round-trip; flattens nested maps to dot keys into the SAME `SpringProperties` model (real key line, `${ENV:default}` placeholders); profile from filename; non-scalar sequences / extra `---` documents / parse errors → `ParseIssue` |
| `sql_init.py` | — | schema/data `.sql` | Idempotency scanner only: `CREATE TABLE IF NOT EXISTS` / `DROP TABLE … IF EXISTS` markers + lines (not a SQL parser) |

## Invariants

- Never hardcode line numbers — locate by structural node, report real range.
- Unsupported syntax → `ParseIssue` (warning or unsupported_construct), never silent.
- No I/O beyond the file content passed in.
