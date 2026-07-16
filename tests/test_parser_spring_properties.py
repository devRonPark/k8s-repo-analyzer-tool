"""Unit tests for the Spring Boot application.properties parser."""

from __future__ import annotations

from repo_analyzer.parsers.spring_properties import (
    parse_spring_properties,
    profile_from_filename,
)

_DEFAULT = """\
# a comment
database=h2
spring.sql.init.schema-locations=classpath*:db/${database}/schema.sql
management.endpoints.web.exposure.include=*
server.port=9000
"""

_PROFILE = """\
database=mysql
spring.datasource.url=${MYSQL_URL:jdbc:mysql://localhost/petclinic}
spring.datasource.username=${MYSQL_USER:petclinic}
spring.datasource.password=${MYSQL_PASS:petclinic}
spring.sql.init.mode=always
"""


def test_profile_from_filename():
    assert profile_from_filename("src/main/resources/application.properties") is None
    assert profile_from_filename("application-mysql.properties") == "mysql"
    assert profile_from_filename("application-postgres.properties") == "postgres"


def test_keys_values_and_lines():
    props = parse_spring_properties(_DEFAULT, "application.properties")
    assert props.profile is None
    db = props.get("database")
    assert db is not None and db.value == "h2" and db.line == 2
    port = props.get("server.port")
    assert port is not None and port.value == "9000"


def test_comments_are_skipped():
    props = parse_spring_properties(_DEFAULT, "application.properties")
    assert all(not e.key.startswith("#") for e in props.entries)


def test_placeholder_extraction_name_and_default():
    props = parse_spring_properties(_PROFILE, "application-mysql.properties")
    assert props.profile == "mysql"
    url = props.get("spring.datasource.url")
    assert url is not None
    assert len(url.placeholders) == 1
    assert url.placeholders[0].name == "MYSQL_URL"
    assert url.placeholders[0].default == "jdbc:mysql://localhost/petclinic"
    pwd = props.get("spring.datasource.password")
    assert pwd is not None and pwd.placeholders[0].name == "MYSQL_PASS"


def test_property_without_placeholder_has_none():
    props = parse_spring_properties(_DEFAULT, "application.properties")
    schema = props.get("spring.sql.init.schema-locations")
    assert schema is not None
    # ${database} is a property reference, not an env placeholder -> still captured.
    assert schema.placeholders[0].name == "database"
    assert schema.placeholders[0].default is None
