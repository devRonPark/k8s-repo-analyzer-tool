from __future__ import annotations

from repo_analyzer.parsers.webxml import parse_webxml

_WEB = """<?xml version="1.0" encoding="UTF-8"?>
<web-app xmlns="http://java.sun.com/xml/ns/javaee" version="3.0">
    <display-name>Shop</display-name>
    <listener>
        <listener-class>org.springframework.web.context.ContextLoaderListener</listener-class>
    </listener>
    <servlet>
        <servlet-name>Dispatcher</servlet-name>
        <servlet-class>com.example.Dispatcher</servlet-class>
        <load-on-startup>1</load-on-startup>
    </servlet>
    <servlet-mapping>
        <servlet-name>Dispatcher</servlet-name>
        <url-pattern>*.action</url-pattern>
    </servlet-mapping>
</web-app>
"""


def test_display_name_and_listener():
    app = parse_webxml(_WEB, "web.xml")
    assert app.display_name == "Shop"
    assert app.listeners[0].value.endswith("ContextLoaderListener")


def test_servlet_and_mapping_with_lines():
    app = parse_webxml(_WEB, "web.xml")
    servlet = app.servlets[0]
    assert servlet.name == "Dispatcher"
    assert servlet.servlet_class == "com.example.Dispatcher"
    assert servlet.load_on_startup == "1"
    mapping = app.servlet_mappings[0]
    assert mapping.url_pattern == "*.action"
    assert app.url_patterns == ["*.action"]
    assert mapping.location.start_line > 0


def test_non_web_app_root_reports_issue():
    app = parse_webxml("<beans/>", "web.xml")
    assert any(i.construct == "webxml_root" for i in app.issues)
