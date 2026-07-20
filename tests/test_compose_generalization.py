"""Category-level regression tests for the compose/Dockerfile analysis path.

These use synthetic repositories (names, ports, env vars differ from any
fixture) to prove the facts are derived from parsed content, and to lock in two
generalization fixes:

1. Secret classification must not flag *metadata about* a secret (an expiration
   duration that merely contains the substring ``PASSWORD``) as a Secret.
2. Container-image facts (base image, non-root ``USER``, migration ``CMD``) must
   be emitted on the compose path too, not only when a repo has no compose file.
"""

from __future__ import annotations

from repo_analyzer.analyzer import analyze_repository
from repo_analyzer.reporters.markdown_reporter import to_markdown
from repo_analyzer.rules.kubernetes_p0 import is_secret


# --------------------------------------------------------------------------- #
# is_secret classification
# --------------------------------------------------------------------------- #
def test_is_secret_flags_real_credentials() -> None:
    assert is_secret("JWT_SECRET")
    assert is_secret("SMTP_PASSWORD")
    assert is_secret("DATABASE_PASSWORD")
    assert is_secret("AWS_SECRET_ACCESS_KEY")


def test_is_secret_ignores_duration_metadata() -> None:
    # Names that merely *describe* a secret (its expiry/rotation policy, length)
    # carry a non-sensitive scalar and must not be classified as secrets.
    assert not is_secret("JWT_RESET_PASSWORD_EXPIRATION_MINUTES")
    assert not is_secret("JWT_ACCESS_EXPIRATION_MINUTES")
    assert not is_secret("TOKEN_TTL_SECONDS")
    assert not is_secret("SECRET_ROTATION_ENABLED")
    assert not is_secret("API_KEY_LENGTH")


_COMPOSE = """\
version: '3'
services:
  web:
    build: .
    ports:
      - '3000:3000'
    env_file:
      - .env
"""

_ENV = """\
PORT=3000
JWT_SECRET=thisisasamplesecret
JWT_RESET_PASSWORD_EXPIRATION_MINUTES=10
SMTP_PASSWORD=email-server-password
"""

_DOCKERFILE_NONROOT = """\
FROM node:18-alpine
RUN adduser -D appuser
WORKDIR /app
COPY . .
USER appuser
EXPOSE 3000
CMD ["node", "src/index.js"]
"""

_DOCKERFILE_MIGRATION = """\
FROM python:3.11-slim
WORKDIR /app
COPY . .
EXPOSE 8000
CMD alembic upgrade head && uvicorn --host=0.0.0.0 app.main:app
"""


def _make_repo(tmp_path, *, dockerfile=_DOCKERFILE_NONROOT, env=_ENV):
    (tmp_path / "docker-compose.yml").write_text(_COMPOSE)
    (tmp_path / "Dockerfile").write_text(dockerfile)
    (tmp_path / ".env.example").write_text(env)
    return analyze_repository(str(tmp_path))


def test_expiration_env_is_config_not_secret(tmp_path) -> None:
    result = _make_repo(tmp_path)
    secret_subjects = {f.subject for f in result.secrets}
    config_subjects = {f.subject for f in result.configuration}
    assert "secret.JWT_SECRET" in secret_subjects
    assert "secret.SMTP_PASSWORD" in secret_subjects
    # The expiration duration is config, not a secret.
    assert "secret.JWT_RESET_PASSWORD_EXPIRATION_MINUTES" not in secret_subjects
    assert "config.JWT_RESET_PASSWORD_EXPIRATION_MINUTES" in config_subjects


def test_compose_path_emits_nonroot_image_fact(tmp_path) -> None:
    result = _make_repo(tmp_path, dockerfile=_DOCKERFILE_NONROOT)
    subjects = {f.subject: f for f in result.container_image}
    assert "image.base" in subjects
    assert subjects["image.base"].value == "node:18-alpine"
    assert "image.non_root" in subjects
    assert subjects["image.non_root"].value == "appuser"


def test_compose_path_surfaces_startup_migration_from_dockerfile(tmp_path) -> None:
    result = _make_repo(tmp_path, dockerfile=_DOCKERFILE_MIGRATION)
    subjects = {f.subject for f in result.container_image}
    assert "image.migration_target" in subjects
    mig = next(f for f in result.container_image if f.subject == "image.migration_target")
    assert "alembic" in mig.value.lower()
    assert mig.evidence and mig.evidence[0].path == "Dockerfile"


def test_migration_question_ports_reflects_component_ports(tmp_path) -> None:
    # The ports/services migration answer must not contradict the per-component
    # ports rendered above it (regression: the old quick answer previously said
    # "none" whenever the port came from a derived finding rather than a compose
    # ``.container_port``).
    result = _make_repo(tmp_path)
    md = to_markdown(result)
    lines = md.splitlines()
    question_index = next(
        index
        for index, line in enumerate(lines)
        if "어떤 Port와 Service가 필요한가?" in line
    )
    answer = next(line for line in lines[question_index:] if "Answer:" in line)
    assert "3000" in answer
    assert "none" not in answer
