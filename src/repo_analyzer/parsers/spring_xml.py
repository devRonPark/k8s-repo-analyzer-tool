"""Focused datasource detection in Spring XML application-context files.

This is deliberately narrow: it only extracts the data-tier facts a Kubernetes
migration needs — whether the app uses an embedded in-process database (and the
init scripts it loads at startup) or an external datasource (and its JDBC URL).
It is not a general Spring bean parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import Located, ParseIssue
from .xml_source import XmlNode, parse_xml


@dataclass
class EmbeddedDatabase:
    db_type: str  # e.g. "HSQL", "H2", "DERBY" (declared or default)
    scripts: list[Located]
    location: Located


@dataclass
class ExternalDatasource:
    bean_class: str
    jdbc_url: str | None
    location: Located


@dataclass
class SpringContext:
    path: str
    is_spring: bool = False
    embedded_databases: list[EmbeddedDatabase] = field(default_factory=list)
    external_datasources: list[ExternalDatasource] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


_DATASOURCE_CLASS_HINTS = (
    "DriverManagerDataSource",
    "BasicDataSource",
    "HikariDataSource",
    "ComboPooledDataSource",
    "SimpleDriverDataSource",
)


def parse_spring_xml(text: str, path: str) -> SpringContext:
    context = SpringContext(path=path)
    doc = parse_xml(text, path)
    context.issues.extend(doc.issues)
    root = doc.root
    if root is None:
        return context
    # Both Spring and CDI use a <beans> root; distinguish by namespace so a CDI
    # WEB-INF/beans.xml is not mistaken for a Spring application context.
    if root.tag != "beans":
        return context
    namespaces = " ".join(
        value for key, value in root.attrib.items() if key == "xmlns" or key.startswith("xmlns")
    )
    if "springframework.org/schema/beans" not in namespaces:
        return context
    context.is_spring = True

    for node in root.iter_tag("embedded-database"):
        db_type = node.attrib.get("type", "HSQL").upper()
        scripts: list[Located] = []
        for script in node.iter_tag("script"):
            location = script.attrib.get("location", "")
            scripts.append(
                Located(
                    value=location,
                    selector="jdbc:script",
                    start_line=script.start_line,
                    end_line=script.end_line,
                )
            )
        context.embedded_databases.append(
            EmbeddedDatabase(
                db_type=db_type,
                scripts=scripts,
                location=Located(
                    value=db_type,
                    selector="jdbc:embedded-database",
                    start_line=node.start_line,
                    end_line=node.end_line,
                ),
            )
        )

    for bean in root.iter_tag("bean"):
        bean_class = bean.attrib.get("class", "")
        if not any(hint in bean_class for hint in _DATASOURCE_CLASS_HINTS):
            continue
        jdbc_url = _property_value(bean, ("url", "jdbcUrl"))
        context.external_datasources.append(
            ExternalDatasource(
                bean_class=bean_class,
                jdbc_url=jdbc_url,
                location=Located(
                    value=bean_class.rsplit(".", 1)[-1],
                    selector="bean[dataSource]",
                    start_line=bean.start_line,
                    end_line=bean.end_line,
                ),
            )
        )

    return context


def _property_value(bean: XmlNode, names: tuple[str, ...]) -> str | None:
    for prop in bean.find("property"):
        if prop.attrib.get("name") in names:
            return prop.attrib.get("value")
    return None
