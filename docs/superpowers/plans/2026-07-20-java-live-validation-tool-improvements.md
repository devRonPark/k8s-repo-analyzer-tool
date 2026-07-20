# Java Migration Question Output Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the analyzer JSON so a developer can understand the Kubernetes migration big picture without reading source code, using the seven migration questions as the only acceptance surface.

**Architecture:** Keep the current analyzer interface and result schema. Deepen rule logic behind `kubernetes_p0.py`, `java_webapp.py`, and related tests so repository facts map more accurately into components, build/run, ports/services, dependencies, config/secrets, persistence, and repository unknowns.

**Tech Stack:** Python 3.12, Pydantic v2, existing `repo_analyzer` parsers/rules, pytest, existing live SGLang runner for final spot checks.

## Global Constraints

- Scope is limited to these seven questions:
  1. What application is this?
  2. How is it built and run?
  3. What ports and Services are needed?
  4. What external dependencies exist?
  5. What ConfigMaps and Secrets are needed?
  6. What data must be persisted?
  7. What cannot be decided from the repository alone?
- Excluded scope: security audit, session internals, cache consistency analysis, SQL race/concurrency analysis, business-code behavior analysis.
- No LLM reads repository files. All facts must come from deterministic parsers and rules.
- Never invent operational values. Replica count, resources, ingress class, HPA, PDB, PVC size, StorageClass, DB HA/backup remain `unresolved` unless explicitly present.
- Preserve deterministic output: stable ordering, repo-relative paths, source-line evidence where available.
- TDD required: write a failing test before each implementation change.

---

## Sequential Improvement Order

1. Component/module matching: prevent JeecgBoot frontend/backend confusion.
2. Promote compose datastores into runtime dependency and persistence answers.
3. Classify local DB images as stateful workloads.
4. Preserve compose `depends_on`.
5. Reflect SQL/Flyway evidence in persistence answers.
6. De-duplicate runtime dependencies.
7. Clarify embedded vs external dependency wording.

---

### Task 1: Component/Module Matching

**Purpose:** Answer Q1, Q2, and Q3 correctly by ensuring Java/Maven facts attach to the backend module/component, not a frontend compose service.

**Files:**
- Modify: `src/repo_analyzer/rules/java_webapp.py`
- Test: `tests/test_java_generalization.py`

**Interfaces:**
- Consumes: `analyze_repository(repository_path, build_system="auto")`
- Produces: better Maven primary module selection and compose component matching behind the existing `AnalysisResult` interface

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_java_generalization.py`:

```python
def test_maven_multi_module_backend_does_not_attach_to_frontend(tmp_path):
    repo = tmp_path
    (repo / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion>"
        "<groupId>demo</groupId><artifactId>root</artifactId>"
        "<version>1.0.0</version><packaging>pom</packaging>"
        "<modules><module>backend</module><module>frontend</module></modules>"
        "</project>",
        encoding="utf-8",
    )
    (repo / "backend").mkdir()
    (repo / "backend" / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion>"
        "<groupId>demo</groupId><artifactId>backend</artifactId>"
        "<version>1.0.0</version><packaging>jar</packaging>"
        "<properties><java.version>17</java.version></properties>"
        "<dependencies><dependency><groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-starter-web</artifactId><version>3.3.0</version>"
        "</dependency></dependencies>"
        "<build><plugins><plugin><groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>"
        "</project>",
        encoding="utf-8",
    )
    (repo / "backend" / "Dockerfile").write_text("FROM eclipse-temurin:17\n", encoding="utf-8")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "Dockerfile").write_text("FROM nginx:1\n", encoding="utf-8")
    (repo / "docker-compose.yml").write_text(
        "services:\n"
        "  backend:\n"
        "    build: ./backend\n"
        "    ports: ['8080:8080']\n"
        "  frontend:\n"
        "    build: ./frontend\n"
        "    ports: ['80:80']\n",
        encoding="utf-8",
    )

    result = analyze_repository(str(repo))
    components = {component.name: component for component in result.components}

    assert components["backend"].language == "Java 17"
    assert components["backend"].build_tool == "Maven"
    assert components["frontend"].language is None
    assert components["frontend"].build_tool is None
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_java_generalization.py::test_maven_multi_module_backend_does_not_attach_to_frontend
```

Expected: FAIL because Java facts can attach to the wrong component or root aggregator.

- [ ] **Step 3: Implement minimal fix**

In `java_webapp.py`:
- Update `_primary_pom` to deprioritize `packaging=pom`.
- Prefer POMs with `spring-boot-maven-plugin`.
- Then prefer `packaging in {"jar", "war"}` with `artifact_id`.
- Keep stable tie-break: shortest path, then lexicographic path.
- In `_match_or_create_component`, prefer a component whose normalized `build_context` equals the selected POM directory or whose Dockerfile equals the selected module Dockerfile.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_java_generalization.py::test_maven_multi_module_backend_does_not_attach_to_frontend
```

Expected: PASS.

---

### Task 2: Compose Datastores As Runtime Dependencies And Persistence

**Purpose:** Answer Q4 and Q6 correctly when compose defines MySQL, PostgreSQL, pgvector, Redis, MongoDB, or MariaDB services.

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_compose_generalization.py`

**Interfaces:**
- Consumes: existing `Component` fields: `name`, `image`, `runtime`, `container_ports`, `environment`
- Produces: `result.runtime_dependencies` and `result.storage` findings using existing `Finding`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_compose_generalization.py`:

```python
def test_compose_datastores_feed_dependency_and_persistence_questions(tmp_path):
    repo = tmp_path
    (repo / "docker-compose.yml").write_text(
        "services:\n"
        "  mysql:\n"
        "    image: custom-mysql-seed\n"
        "    environment:\n"
        "      MYSQL_ROOT_PASSWORD: root\n"
        "    ports: ['3306:3306']\n"
        "  redis:\n"
        "    image: redis:7\n"
        "  pgvector:\n"
        "    image: pgvector/pgvector:pg16\n"
        "    environment:\n"
        "      POSTGRES_PASSWORD: postgres\n"
        "  app:\n"
        "    image: app\n"
        "    depends_on: [mysql, redis, pgvector]\n"
        "    ports: ['8080:8080']\n",
        encoding="utf-8",
    )

    result = analyze_repository(str(repo))
    deps = {finding.subject: finding.value for finding in result.runtime_dependencies}
    persistent = next(q for q in result.migration_questions if q.id == "persistent_data")
    external = next(q for q in result.migration_questions if q.id == "external_dependencies")

    assert deps["compose.mysql"] == "MySQL"
    assert deps["compose.redis"] == "Redis"
    assert deps["compose.pgvector"] == "PostgreSQL / pgvector"
    assert persistent.status in {"answered", "partial"}
    assert "MySQL" in persistent.answer
    assert "Redis" in external.answer
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_compose_generalization.py::test_compose_datastores_feed_dependency_and_persistence_questions
```

Expected: FAIL because compose datastore components are not promoted into runtime dependency/persistence answers.

- [ ] **Step 3: Implement deterministic datastore classifier**

Add a private helper in `kubernetes_p0.py`:

```python
def _compose_datastore_kind(component: Component) -> str | None:
    tokens = " ".join(
        [
            component.name,
            component.image or "",
            component.runtime or "",
            " ".join(component.environment),
            " ".join(str(port) for port in component.container_ports),
        ]
    ).lower()
    ...
```

Classifier mapping:
- MySQL: `mysql`, port `3306`, `MYSQL_ROOT_PASSWORD`
- MariaDB: `mariadb`
- PostgreSQL: `postgres`, `postgresql`, port `5432`, `POSTGRES_PASSWORD`
- PostgreSQL / pgvector: `pgvector`
- Redis: `redis`, port `6379`
- MongoDB: `mongo`, port `27017`

Emit one finding per datastore component:

```python
Finding(
    subject=f"compose.{component.name}",
    value=kind,
    confidence="explicit",
    kubernetes_effect="runtime dependency for migration topology; managed service vs in-cluster workload remains an operational decision",
    evidence=[...compose service evidence when available...],
)
```

Also emit a storage finding for database-like datastores except Redis:

```python
Finding(
    subject=f"storage.{component.name}.database_persistence",
    value=f"{kind} data requires persistence if run in-cluster; managed service replacement remains unresolved",
    confidence="derived",
    kubernetes_effect="PVC/StatefulSet volumeClaimTemplate or managed database persistence decision",
    evidence=[...],
)
```

- [ ] **Step 4: Verify GREEN**

Run the targeted test. Expected: PASS.

---

### Task 3: Local DB Images As Stateful Workloads

**Purpose:** Answer Q3 and Q7 correctly by mapping local DB-like images to StatefulSet candidates with persistence-related unresolved inputs.

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_compose_generalization.py`

**Interfaces:**
- Consumes: `_compose_datastore_kind(component: Component) -> str | None` from Task 2
- Produces: corrected `WorkloadMapping.kubernetes_kind`

- [ ] **Step 1: Write the failing test**

Add this test:

```python
def test_local_mysql_image_maps_to_stateful_workload(tmp_path):
    repo = tmp_path
    (repo / "docker-compose.yml").write_text(
        "services:\n"
        "  mysql:\n"
        "    image: custom-mysql-seed\n"
        "    environment:\n"
        "      MYSQL_ROOT_PASSWORD: root\n"
        "    ports: ['13306:3306']\n",
        encoding="utf-8",
    )

    result = analyze_repository(str(repo))
    mapping = next(item for item in result.workload_mappings if item.component == "mysql")

    assert "StatefulSet" in mapping.kubernetes_kind
    assert "PVC size" in mapping.unresolved
    assert "StorageClass" in mapping.unresolved
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_compose_generalization.py::test_local_mysql_image_maps_to_stateful_workload
```

Expected: FAIL because the local MySQL-like service maps to Deployment.

- [ ] **Step 3: Reuse datastore classifier in workload mapping**

In workload mapping logic, if `_compose_datastore_kind(component)` is a database-like datastore, use:

```python
"StatefulSet + headless Service (or external managed database)"
```

Include unresolved:

```python
["replica count", "CPU/memory", "PVC size", "StorageClass", "DB HA & backup policy"]
```

Redis may stay stateful unless repository evidence proves it is only a cache and persistence is intentionally disabled; do not add cache consistency analysis.

- [ ] **Step 4: Verify GREEN**

Run the targeted test. Expected: PASS.

---

### Task 4: Preserve Compose `depends_on`

**Purpose:** Answer Q2, Q4, and Q7 better by preserving startup/dependency topology without inspecting application internals.

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_compose_generalization.py`

**Interfaces:**
- Consumes: parsed `ComposeService.depends_on`
- Produces: populated `Component.depends_on` and source-backed `startup_order`

- [ ] **Step 1: Write the failing test**

Add this test:

```python
def test_compose_depends_on_is_preserved_on_component_and_startup_order(tmp_path):
    repo = tmp_path
    (repo / "docker-compose.yml").write_text(
        "services:\n"
        "  mysql:\n"
        "    image: mysql:8\n"
        "  redis:\n"
        "    image: redis:7\n"
        "  app:\n"
        "    image: app\n"
        "    depends_on:\n"
        "      - mysql\n"
        "      - redis\n"
        "    ports: ['8080:8080']\n",
        encoding="utf-8",
    )

    result = analyze_repository(str(repo))
    app = next(component for component in result.components if component.name == "app")

    assert app.depends_on == ["mysql", "redis"]
    assert any("mysql" in str(finding.value) for finding in result.startup_order)
    assert any("redis" in str(finding.value) for finding in result.startup_order)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_compose_generalization.py::test_compose_depends_on_is_preserved_on_component_and_startup_order
```

Expected: FAIL because component dependency names are missing.

- [ ] **Step 3: Implement preservation**

In `_component_from_service`, copy dependency service names from `service.depends_on` into `component.depends_on`, sorted by original compose order with deterministic de-duplication.

Ensure startup findings mention actual dependency names and attach compose evidence where available.

- [ ] **Step 4: Verify GREEN**

Run the targeted test. Expected: PASS.

---

### Task 5: SQL/Flyway Persistence Evidence

**Purpose:** Answer Q6 using SQL/Flyway evidence only at migration-big-picture level. Do not analyze SQL race conditions, lock behavior, or migration concurrency.

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_migration_questions.py`
- Test: `tests/test_parser_sql_init.py`

**Interfaces:**
- Consumes: existing SQL parser output and existing `result.storage`
- Produces: storage/persistence basis for Q6

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_migration_questions.py`:

```python
def test_persistent_data_uses_sql_flyway_evidence_without_volumes(tmp_path):
    repo = tmp_path
    sql_dir = repo / "src" / "main" / "resources" / "flyway" / "sql" / "mysql"
    sql_dir.mkdir(parents=True)
    (sql_dir / "V1__init.sql").write_text(
        "CREATE TABLE owners (id bigint primary key);\n",
        encoding="utf-8",
    )
    (repo / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion>"
        "<groupId>demo</groupId><artifactId>app</artifactId>"
        "<version>1.0.0</version><packaging>jar</packaging>"
        "<properties><java.version>17</java.version></properties>"
        "</project>",
        encoding="utf-8",
    )

    result = analyze_repository(str(repo))
    question = next(q for q in result.migration_questions if q.id == "persistent_data")

    assert question.status == "partial"
    assert "SQL" in question.answer or "schema" in question.answer
    assert question.basis
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_persistent_data_uses_sql_flyway_evidence_without_volumes
```

Expected: FAIL because SQL evidence is not reflected in persistent data.

- [ ] **Step 3: Implement persistence finding**

When SQL init/migration evidence exists, add a storage finding:

```python
Finding(
    subject="storage.database_schema",
    value={"tables": sorted(table_names), "source": "sql"},
    confidence="explicit",
    kubernetes_effect="database persistence exists; PVC/managed DB choice remains operational",
    evidence=[...line-located SQL evidence...],
)
```

If table names are not available, still emit a finding with source paths. Do not infer schema semantics beyond table/migration presence.

- [ ] **Step 4: Verify GREEN**

Run the targeted test. Expected: PASS.

---

### Task 6: Runtime Dependency De-Duplication

**Purpose:** Keep Q4 and Q6 readable by removing repeated identical dependencies, especially in multi-module/profile repos such as macrozheng/mall.

**Files:**
- Modify: `src/repo_analyzer/rules/java_webapp.py`
- Modify: `src/repo_analyzer/rules/spring_boot.py`
- Test: `tests/test_java_generalization.py`

**Interfaces:**
- Consumes: candidate `Finding`
- Produces: unique findings by `(subject, value)` with deterministic evidence

- [ ] **Step 1: Write the failing test**

Add this test:

```python
def test_runtime_dependencies_are_deduplicated_by_subject_and_value(tmp_path):
    repo = tmp_path
    (repo / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion>"
        "<groupId>demo</groupId><artifactId>app</artifactId>"
        "<version>1.0.0</version><packaging>jar</packaging>"
        "<dependencies><dependency><groupId>mysql</groupId>"
        "<artifactId>mysql-connector-java</artifactId><version>8.0.33</version>"
        "</dependency></dependencies></project>",
        encoding="utf-8",
    )
    resources = repo / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application-dev.yml").write_text(
        "spring:\n"
        "  datasource:\n"
        "    url: jdbc:mysql://db/app\n",
        encoding="utf-8",
    )
    (resources / "application-prod.yml").write_text(
        "spring:\n"
        "  datasource:\n"
        "    url: jdbc:mysql://db/app\n",
        encoding="utf-8",
    )

    result = analyze_repository(str(repo))
    deps = [(finding.subject, finding.value) for finding in result.runtime_dependencies]

    assert deps.count(("database.dev", "External MySQL")) <= 1
    assert len(deps) == len(dict.fromkeys(deps))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_java_generalization.py::test_runtime_dependencies_are_deduplicated_by_subject_and_value
```

Expected: FAIL if identical dependency findings are repeated.

- [ ] **Step 3: Implement helper**

Add a private helper in each affected rule module or a shared local helper in `kubernetes_p0.py` if already imported there:

```python
def _append_unique_finding(findings: list[Finding], finding: Finding) -> None:
    key = (finding.subject, jsonable_stable_value(finding.value))
    ...
```

Avoid importing heavy serialization. For current values, `repr(finding.value)` is acceptable only if the value is a deterministic scalar/list/dict already sorted.

- [ ] **Step 4: Verify GREEN**

Run the targeted test. Expected: PASS.

---

### Task 7: Embedded Vs External Dependency Wording

**Purpose:** Keep Q4 semantically clear. Embedded in-process datastores should be visible, but not described as external services.

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_migration_questions.py`
- Test: `tests/test_golden_jpetstore.py`
- Test: `tests/test_golden_spring_petclinic.py`

**Interfaces:**
- Consumes: `result.runtime_dependencies`
- Produces: clearer `MigrationQuestionAnswer` for `external_dependencies`

- [ ] **Step 1: Write the failing test**

Add this test:

```python
def test_external_dependencies_distinguishes_embedded_datastores(jpetstore_repo):
    result = analyze_repository(str(jpetstore_repo))
    question = next(q for q in result.migration_questions if q.id == "external_dependencies")

    assert "embedded HSQL" in question.answer
    assert "external service" not in question.answer.lower()
    assert "embedded" in question.answer.lower()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_external_dependencies_distinguishes_embedded_datastores
```

Expected: FAIL if embedded dependencies are phrased as external services or the answer is ambiguous.

- [ ] **Step 3: Implement grouped wording**

Keep question id `external_dependencies` for compatibility, but render answer groups:

```text
External services: ...
Embedded/in-process datastores: ...
```

If no external services exist but embedded datastores exist, answer:

```text
No external service was detected. Embedded/in-process datastores: database.embedded: embedded HSQL ...
```

Do not add security audit or cache consistency wording.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_external_dependencies_distinguishes_embedded_datastores
```

Expected: PASS.

---

## Final Verification

- [ ] **Step 1: Run focused Java and migration tests**

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_compose_generalization.py tests/test_java_generalization.py tests/test_migration_questions.py tests/test_golden_jpetstore.py tests/test_golden_spring_petclinic.py
```

Expected: PASS.

- [ ] **Step 2: Run structural validation against all 10 required Java repos**

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_external_repos.py --workdir /tmp/repo-analyzer-validation --output /tmp/required-java-repos-after-question-improvements.md --skip-clone
```

Expected: exit 0.

- [ ] **Step 3: Run live SGLang validation one repo at a time for repos 1-5**

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_sglang_live_repos.py --repo mybatis/jpetstore-6 --output /tmp/live-jpetstore-after.json
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_sglang_live_repos.py --repo spring-projects/spring-petclinic --output /tmp/live-petclinic-after.json
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_sglang_live_repos.py --repo jhipster/jhipster-sample-app --output /tmp/live-jhipster-after.json
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_sglang_live_repos.py --repo macrozheng/mall --output /tmp/live-mall-after.json
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_sglang_live_repos.py --repo jeecgboot/JeecgBoot --output /tmp/live-jeecgboot-after.json
```

Expected: each JSON contains one row with `ok=true`, `tool_ok=true`, and non-empty `final_answer`.

- [ ] **Step 4: Run full test suite**

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Expected: PASS.

---

## Self-Review

- Scope check: Every task maps directly to at least one of the seven migration questions.
- Exclusion check: No task adds security audit, session internals, cache consistency analysis, SQL race analysis, or business-code analysis.
- Placeholder scan: No placeholder implementation steps remain.
- Type consistency: The plan uses existing modules and result types: `AnalysisResult`, `Component`, `Finding`, `WorkloadMapping`, and `MigrationQuestionAnswer`.
