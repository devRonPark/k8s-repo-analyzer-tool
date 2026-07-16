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

## Invariants

- Never hardcode line numbers — locate by structural node, report real range.
- Unsupported syntax → `ParseIssue` (warning or unsupported_construct), never silent.
- No I/O beyond the file content passed in.
