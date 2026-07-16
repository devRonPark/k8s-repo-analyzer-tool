from __future__ import annotations

from repo_analyzer.parsers.spring_xml import parse_spring_xml

_EMBEDDED = """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:jdbc="http://www.springframework.org/schema/jdbc">
    <jdbc:embedded-database id="dataSource">
        <jdbc:script location="classpath:database/schema.sql"/>
        <jdbc:script location="classpath:database/data.sql"/>
    </jdbc:embedded-database>
</beans>
"""

_EXTERNAL = """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans">
    <bean id="dataSource" class="org.springframework.jdbc.datasource.DriverManagerDataSource">
        <property name="url" value="jdbc:mysql://db:3306/shop"/>
        <property name="username" value="app"/>
    </bean>
</beans>
"""

# CDI beans.xml: same <beans> root, different (javaee) namespace.
_CDI = """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://xmlns.jcp.org/xml/ns/javaee" version="1.1" bean-discovery-mode="all"/>
"""


def test_embedded_database_and_scripts():
    ctx = parse_spring_xml(_EMBEDDED, "applicationContext.xml")
    assert ctx.is_spring is True
    assert len(ctx.embedded_databases) == 1
    db = ctx.embedded_databases[0]
    assert db.db_type == "HSQL"  # default when type attr omitted
    assert [s.value for s in db.scripts] == [
        "classpath:database/schema.sql",
        "classpath:database/data.sql",
    ]
    assert db.scripts[0].start_line > 0


def test_external_datasource_url_extracted():
    ctx = parse_spring_xml(_EXTERNAL, "applicationContext.xml")
    assert ctx.is_spring is True
    assert not ctx.embedded_databases
    ds = ctx.external_datasources[0]
    assert ds.jdbc_url == "jdbc:mysql://db:3306/shop"
    assert "DriverManagerDataSource" in ds.bean_class


def test_cdi_beans_xml_is_not_spring():
    ctx = parse_spring_xml(_CDI, "beans.xml")
    assert ctx.is_spring is False
    assert ctx.embedded_databases == []
    assert ctx.external_datasources == []
