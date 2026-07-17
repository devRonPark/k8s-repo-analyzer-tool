"""Unit tests for the Spring Boot application*.yml / .yaml parser.

The YAML parser flattens nested mappings into the SAME dot-keyed
``SpringProperties`` model the ``.properties`` parser produces, so the
Spring/Java rules consume both formats identically.
"""

from __future__ import annotations

from repo_analyzer.parsers.spring_yaml import (
    parse_spring_yaml,
    profile_from_yaml_filename,
)

# Lines are asserted below, so keep this literal stable.
_APP = """\
server:
  port: 8080
spring:
  datasource:
    url: ${DB_URL:jdbc:postgresql://localhost:5432/app}
    username: ${DB_USER:app}
    password: ${DB_PASS:app}
management:
  endpoints:
    web:
      exposure:
        include: "health,info,prometheus"
springdoc:
  swagger-ui:
    enabled: ${SWAGGER_UI_ENABLED:false}
featureflags:
  - alpha
  - beta
"""

_PROD = """\
spring:
  datasource:
    url: jdbc:postgresql://db:5432/prod
  liquibase:
    contexts: prod
"""


def test_profile_from_yaml_filename():
    assert profile_from_yaml_filename("src/main/resources/application.yml") is None
    assert profile_from_yaml_filename("application.yaml") is None
    assert profile_from_yaml_filename("config/application-prod.yml") == "prod"
    assert profile_from_yaml_filename("application-dev.yaml") == "dev"


def test_flatten_keys_values_and_lines():
    props = parse_spring_yaml(_APP, "application.yml")
    assert props.profile is None
    port = props.get("server.port")
    assert port is not None and port.value == "8080" and port.line == 2
    url = props.get("spring.datasource.url")
    assert url is not None and url.line == 5
    inc = props.get("management.endpoints.web.exposure.include")
    assert inc is not None and inc.value == "health,info,prometheus" and inc.line == 12


def test_env_placeholder_extraction():
    props = parse_spring_yaml(_APP, "application.yml")
    url = props.get("spring.datasource.url")
    assert url.placeholders[0].name == "DB_URL"
    assert url.placeholders[0].default == "jdbc:postgresql://localhost:5432/app"
    pwd = props.get("spring.datasource.password")
    assert pwd is not None and pwd.placeholders[0].name == "DB_PASS"


def test_boolean_scalar_normalised():
    props = parse_spring_yaml(_APP, "application.yml")
    swagger = props.get("springdoc.swagger-ui.enabled")
    # value is a ${...} string here; ensure boolean handling elsewhere:
    assert swagger is not None and swagger.placeholders[0].name == "SWAGGER_UI_ENABLED"
    bools = parse_spring_yaml("a:\n  b: true\n  c: false\n", "application.yml")
    assert bools.get("a.b").value == "true"
    assert bools.get("a.c").value == "false"


def test_scalar_sequence_joined_with_comma():
    props = parse_spring_yaml(_APP, "application.yml")
    ff = props.get("featureflags")
    assert ff is not None and ff.value == "alpha,beta" and ff.line == 16


def test_profile_file_and_datasource():
    props = parse_spring_yaml(_PROD, "application-prod.yml")
    assert props.profile == "prod"
    url = props.get("spring.datasource.url")
    assert url is not None and url.value == "jdbc:postgresql://db:5432/prod"


def test_non_scalar_sequence_is_reported_not_dropped():
    text = "clusters:\n  - name: a\n    port: 1\n  - name: b\n    port: 2\n"
    props = parse_spring_yaml(text, "application.yml")
    assert props.get("clusters") is None
    assert any(i.construct == "spring_yaml_sequence" for i in props.issues)


def test_extra_document_is_reported():
    text = "server:\n  port: 8080\n---\nspring:\n  config:\n    activate:\n      on-profile: dev\n"
    props = parse_spring_yaml(text, "application.yml")
    assert props.get("server.port").value == "8080"
    assert any(i.construct == "spring_yaml_extra_document" for i in props.issues)


def test_malformed_yaml_is_reported_not_raised():
    props = parse_spring_yaml("a:\n  b: [unterminated\n", "application.yml")
    assert any(i.construct == "yaml_parse_error" for i in props.issues)
    assert props.entries == []
