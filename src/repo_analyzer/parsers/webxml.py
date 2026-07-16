"""Servlet deployment descriptor (``web.xml``) parser with source lines.

Extracts servlets, filters, listeners, context-params and servlet mappings so
the rule engine can describe HTTP entry points and startup listeners for a
Java web application. The context *path* is intentionally not read here: it is a
deployment property (WAR name / container config), not a ``web.xml`` value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import Located, ParseIssue
from .xml_source import XmlNode, parse_xml


@dataclass
class Servlet:
    name: str
    servlet_class: str | None
    load_on_startup: str | None
    location: Located


@dataclass
class ServletMapping:
    servlet_name: str
    url_pattern: str
    location: Located


@dataclass
class WebApp:
    path: str
    display_name: str | None = None
    context_params: list[Located] = field(default_factory=list)
    listeners: list[Located] = field(default_factory=list)
    filters: list[Located] = field(default_factory=list)
    servlets: list[Servlet] = field(default_factory=list)
    servlet_mappings: list[ServletMapping] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def url_patterns(self) -> list[str]:
        return [m.url_pattern for m in self.servlet_mappings]


def parse_webxml(text: str, path: str) -> WebApp:
    app = WebApp(path=path)
    doc = parse_xml(text, path)
    app.issues.extend(doc.issues)
    root = doc.root
    if root is None or root.tag != "web-app":
        if not app.issues:
            app.issues.append(ParseIssue("webxml_root", "no <web-app> root element"))
        return app

    app.display_name = root.text_of("display-name")

    for param in root.find("context-param"):
        name = param.text_of("param-name") or ""
        app.context_params.append(
            Located(
                value=name,
                selector=f"context-param[{name}]",
                start_line=param.start_line,
                end_line=param.end_line,
            )
        )

    for listener in root.find("listener"):
        cls = listener.text_of("listener-class") or ""
        app.listeners.append(
            Located(
                value=cls,
                selector="listener-class",
                start_line=listener.start_line,
                end_line=listener.end_line,
            )
        )

    for flt in root.find("filter"):
        name = flt.text_of("filter-name") or ""
        app.filters.append(
            Located(
                value=name,
                selector=f"filter[{name}]",
                start_line=flt.start_line,
                end_line=flt.end_line,
            )
        )

    for servlet in root.find("servlet"):
        name = servlet.text_of("servlet-name") or ""
        app.servlets.append(
            Servlet(
                name=name,
                servlet_class=servlet.text_of("servlet-class"),
                load_on_startup=servlet.text_of("load-on-startup"),
                location=Located(
                    value=name,
                    selector=f"servlet[{name}]",
                    start_line=servlet.start_line,
                    end_line=servlet.end_line,
                ),
            )
        )

    for mapping in root.find("servlet-mapping"):
        servlet_name = mapping.text_of("servlet-name") or ""
        pattern = mapping.text_of("url-pattern") or ""
        app.servlet_mappings.append(
            ServletMapping(
                servlet_name=servlet_name,
                url_pattern=pattern,
                location=Located(
                    value=pattern,
                    selector=f"servlet-mapping[{servlet_name}]",
                    start_line=mapping.start_line,
                    end_line=mapping.end_line,
                ),
            )
        )

    return app
