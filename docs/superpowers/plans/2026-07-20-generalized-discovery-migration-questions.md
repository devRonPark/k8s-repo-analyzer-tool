# Generalized Discovery Migration Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add generalized file/content discovery and a deterministic evidence-backed seven-question migration summary without repository-name-specific rules.

**Architecture:** Keep the existing inventory -> parser -> rule -> reporter flow. Inventory finds broad file-class candidates by filename pattern and lightweight content sniffing; parsers confirm file semantics and attach line-located facts; rules build question answers only from existing `AnalysisResult` facts, coverage gaps, and unresolved inputs.

**Tech Stack:** Python 3.12, Pydantic v2, ruamel.yaml, pytest, existing `repo_analyzer` modules.

## Global Constraints

- Do not hardcode repository names such as `jpetstore`, `petclinic`, `jhipster`, or `mall` in production code.
- Prefer file-class and content patterns over fixed paths.
- Treat `docs/`, `document/`, `examples/`, `sample/`, `test/`, and `e2e/` deployment files as supplemental evidence unless selected by README, Compose build context, or an existing primary file.
- If a README command or explicit build/deployment reference selects a file under `docs/`, `document/`, `examples/`, `sample/`, `test/`, or `e2e/`, classify that file as selected primary evidence.
- Broad SQL/YAML candidate discovery must skip files larger than 10 MiB and record the skip as a coverage gap.
- Kubernetes manifest parsing is limited to P0 fields: `apiVersion`, `kind`, `metadata.name`, Service ports, container ports, environment variable names, ConfigMap references, and Secret references.
- Kubernetes manifest facts are explicit basis for the seven migration questions, but they do not override app-source or Compose-derived facts. Conflicts are reported as warnings/unresolved inputs.
- Keep "not detected", "none detected", "partial", and "unresolved" distinct.
- Do not generate Kubernetes manifests.
- Do not invent operational defaults for replica count, CPU/memory, ingress host, TLS, StorageClass, Secret values, or production database endpoints.
- Every seven-question answer must have `status`, `basis`, and `missing` fields.
- Run targeted pytest for each task, then run the full test suite at the end.
- Final validation must run against exactly these 10 repositories: `mybatis/jpetstore-6`, `spring-projects/spring-petclinic`, `jhipster/jhipster-sample-app`, `macrozheng/mall`, `jeecgboot/JeecgBoot`, `apache/guacamole-client`, `apache/ofbiz-framework`, `openmrs/openmrs-core`, `shopizer-ecommerce/shopizer`, and `halo-dev/halo`.
- External repository validation must record the analyzed commit SHA for each repository.
- External repository validation must include structural checks plus 2-3 representative evidence samples per repository; structure-only validation is not enough.
- Source conflict warnings and skipped large candidates must appear in the validation report, but they do not fail external repository validation by themselves.

---

## File Structure

- Modify `src/repo_analyzer/models.py`: add source coverage and migration question answer models, then add top-level fields to `AnalysisResult`.
- Modify `src/repo_analyzer/inventory.py`: broaden SQL discovery, add K8s YAML candidate discovery, and classify evidence path role.
- Modify `src/repo_analyzer/analyzer.py`: parse broadened SQL files, parse K8s manifests, and pass all parsed facts to rules.
- Create `src/repo_analyzer/parsers/kubernetes_yaml.py`: confirm YAML documents with Kubernetes `apiVersion` and `kind`.
- Modify `src/repo_analyzer/parsers/sql_init.py`: classify SQL scripts by content, not filename.
- Modify `src/repo_analyzer/rules/kubernetes_p0.py`: emit coverage matrix and build deterministic seven-question answers from existing findings.
- Modify `src/repo_analyzer/reporters/markdown_reporter.py`: replace `Quick answers` with `Migration questions`.
- Modify tests:
  - `tests/test_inventory_generalized_discovery.py`
  - `tests/test_parser_kubernetes_yaml.py`
  - `tests/test_parser_sql_init.py`
  - `tests/test_migration_questions.py`
  - existing golden tests where output shape changes.
- Regenerate examples after tests pass:
  - `examples/jpetstore-analysis.json`
  - `examples/jpetstore-report.md`
  - `examples/spring-petclinic-analysis.json`
  - `examples/spring-petclinic-report.md`
- Create `scripts/validate_external_repos.py`: clone or reuse the 10 required repositories under `/tmp/repo-analyzer-validation`, run the analyzer, and write a deterministic Markdown validation summary.
- Create `docs/validation/2026-07-20-required-java-repos.md`: generated validation result for the 10 required repositories.

---

### Task 1: Add Source Coverage and Migration Question Models

**Files:**
- Modify: `src/repo_analyzer/models.py`
- Test: `tests/test_migration_questions.py`

**Interfaces:**
- Produces: `SourceCoverage`, `AnswerBasis`, `MigrationQuestionAnswer`
- Updates: `AnalysisResult.source_coverage: list[SourceCoverage]`
- Updates: `AnalysisResult.migration_questions: list[MigrationQuestionAnswer]`

- [ ] **Step 1: Write the failing model test**

Create `tests/test_migration_questions.py`:

```python
from repo_analyzer.models import (
    AnalysisResult,
    AnswerBasis,
    MigrationQuestionAnswer,
    RepositoryMetadata,
    SourceCoverage,
)


def test_analysis_result_accepts_source_coverage_and_migration_questions():
    result = AnalysisResult(
        repository=RepositoryMetadata(
            name="sample",
            profile="kubernetes-p0",
            file_count=1,
        ),
        source_coverage=[
            SourceCoverage(
                source_class="sql",
                status="present",
                paths=["db/init/customer-schema.sql"],
                role="primary",
                detection="extension .sql plus CREATE TABLE content",
            )
        ],
        migration_questions=[
            MigrationQuestionAnswer(
                id="persistent_data",
                question="어떤 데이터가 영속되어야 하는가?",
                status="partial",
                answer="Database schema was detected, but production database storage policy is unresolved.",
                basis=[
                    AnswerBasis(
                        source_section="storage",
                        subject="database.schema",
                        evidence=[],
                    )
                ],
                missing=["production database StorageClass/managed service decision"],
            )
        ],
    )

    dumped = result.model_dump(mode="json")
    assert dumped["source_coverage"][0]["source_class"] == "sql"
    assert dumped["migration_questions"][0]["id"] == "persistent_data"
    assert dumped["migration_questions"][0]["status"] == "partial"
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_analysis_result_accepts_source_coverage_and_migration_questions
```

Expected: FAIL with import errors for the new model classes.

- [ ] **Step 3: Implement the models**

In `src/repo_analyzer/models.py`, add after `Warning`:

```python
QuestionStatus = Literal["answered", "partial", "unresolved", "not_detected"]
CoverageStatus = Literal["present", "missing", "ignored", "error"]
CoverageRole = Literal["primary", "selected_primary", "supplemental", "sample_or_documented_deployment", "test_only"]


class SourceCoverage(_Model):
    source_class: str
    status: CoverageStatus
    paths: list[str] = Field(default_factory=list)
    role: CoverageRole = "primary"
    detection: str


class AnswerBasis(_Model):
    source_section: str
    subject: str
    evidence: list[Evidence] = Field(default_factory=list)


class MigrationQuestionAnswer(_Model):
    id: str
    question: str
    status: QuestionStatus
    answer: str
    basis: list[AnswerBasis] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
```

In `AnalysisResult`, insert these fields after `detected_files` so JSON readers see coverage before derived answers:

```python
    source_coverage: list[SourceCoverage] = Field(default_factory=list)
    migration_questions: list[MigrationQuestionAnswer] = Field(default_factory=list)
```

- [ ] **Step 4: Run the test and verify it passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_analysis_result_accepts_source_coverage_and_migration_questions
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/models.py tests/test_migration_questions.py
git commit -m "feat: add migration question result models"
```

---

### Task 2: Generalize Inventory Discovery for SQL and Kubernetes YAML

**Files:**
- Modify: `src/repo_analyzer/inventory.py`
- Test: `tests/test_inventory_generalized_discovery.py`

**Interfaces:**
- Produces: `Inventory.kubernetes_yaml_files: list[str]`
- Produces: `Inventory.skipped_large_candidates: list[str]`
- Changes: `Inventory.sql_init_files` includes all `.sql` files outside skipped dirs.
- Produces detected kinds: `sql-candidate`, `kubernetes-yaml-candidate`, `candidate-skipped-large`

- [ ] **Step 1: Write failing discovery tests**

Create `tests/test_inventory_generalized_discovery.py`:

```python
from repo_analyzer.inventory import build_inventory


def test_discovers_sql_by_extension_not_filename(tmp_path):
    sql = tmp_path / "database" / "jpetstore-hsqldb-schema.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text("create table account (id int);\n")

    inv = build_inventory(tmp_path)

    assert inv.sql_init_files == ["database/jpetstore-hsqldb-schema.sql"]
    detected = {(d.path, d.kind) for d in inv.detected}
    assert ("database/jpetstore-hsqldb-schema.sql", "sql-candidate") in detected


def test_discovers_kubernetes_yaml_by_content_not_path(tmp_path):
    manifest = tmp_path / "deploy" / "prod" / "app.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
    )

    inv = build_inventory(tmp_path)

    assert inv.kubernetes_yaml_files == ["deploy/prod/app.yaml"]
    detected = {(d.path, d.kind) for d in inv.detected}
    assert ("deploy/prod/app.yaml", "kubernetes-yaml-candidate") in detected


def test_does_not_mark_plain_yaml_as_kubernetes(tmp_path):
    config = tmp_path / "config" / "settings.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("feature: true\n")

    inv = build_inventory(tmp_path)

    assert inv.kubernetes_yaml_files == []


def test_skips_large_sql_candidate_and_records_it(tmp_path):
    sql = tmp_path / "db" / "huge.sql"
    sql.parent.mkdir()
    sql.write_text(" " * (10 * 1024 * 1024 + 1))

    inv = build_inventory(tmp_path)

    assert inv.sql_init_files == []
    assert inv.skipped_large_candidates == ["db/huge.sql"]
    detected = {(d.path, d.kind) for d in inv.detected}
    assert ("db/huge.sql", "candidate-skipped-large") in detected


def test_skipped_large_candidate_paths_are_deduplicated(tmp_path):
    manifest = tmp_path / "deploy.yaml"
    manifest.write_text(" " * (10 * 1024 * 1024 + 1))

    inv = build_inventory(tmp_path)

    assert inv.skipped_large_candidates == ["deploy.yaml"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_inventory_generalized_discovery.py
```

Expected: FAIL because `kubernetes_yaml_files` does not exist and SQL discovery only accepts `schema.sql`/`data.sql`.

- [ ] **Step 3: Implement generalized candidates**

In `Inventory`, add:

```python
    kubernetes_yaml_files: list[str] = field(default_factory=list)
    skipped_large_candidates: list[str] = field(default_factory=list)
```

Add the candidate size constant:

```python
MAX_CANDIDATE_BYTES = 10 * 1024 * 1024
```

Add a helper:

```python
def _too_large_for_candidate_parse(path: Path) -> bool:
    try:
        return path.stat().st_size > MAX_CANDIDATE_BYTES
    except OSError:
        return False
```

Replace `_is_sql_init()` with:

```python
def _is_sql_candidate(name: str) -> bool:
    return name.lower().endswith(".sql")
```

Add lightweight K8s YAML sniffing:

```python
import re

_K8S_KIND_RE = re.compile(r"(?m)^\s*kind\s*:\s*[\"']?(?P<kind>[A-Za-z][A-Za-z0-9]*)[\"']?\s*$")

_K8S_KINDS = {
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Service",
    "Ingress",
    "ConfigMap",
    "Secret",
    "Job",
    "CronJob",
    "PersistentVolumeClaim",
}


def _looks_like_kubernetes_yaml(path: Path) -> bool:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        return False
    if _too_large_for_candidate_parse(path):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "apiVersion:" not in text or "kind:" not in text:
        return False
    return any(match.group("kind") in _K8S_KINDS for match in _K8S_KIND_RE.finditer(text))
```

In `build_inventory()`, replace:

```python
        elif _is_sql_init(name):
            inv.sql_init_files.append(rel)
```

with:

```python
        elif _is_sql_candidate(name):
            if _too_large_for_candidate_parse(path):
                inv.skipped_large_candidates.append(rel)
            else:
                inv.sql_init_files.append(rel)
```

Add this after Spring YAML detection so `application.yml` remains Spring config when it has the Spring application filename pattern:

```python
        if _too_large_for_candidate_parse(path) and path.suffix.lower() in {".yml", ".yaml"}:
            inv.skipped_large_candidates.append(rel)
        elif _looks_like_kubernetes_yaml(path):
            inv.kubernetes_yaml_files.append(rel)
```

In `_build_detected()`, change SQL kind and add K8s:

```python
    detected += [DetectedFile(path=p, kind="sql-candidate") for p in inv.sql_init_files]
    detected += [DetectedFile(path=p, kind="kubernetes-yaml-candidate") for p in inv.kubernetes_yaml_files]
    detected += [DetectedFile(path=p, kind="candidate-skipped-large") for p in inv.skipped_large_candidates]
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_inventory_generalized_discovery.py
```

Expected: PASS.

- [ ] **Step 5: Run affected existing tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_parser_sql_init.py tests/test_compose_discovery.py
```

Expected: PASS. If golden tests fail only because detected kind changed from `sql-init` to `sql-candidate`, update assertions to the new kind.

- [ ] **Step 6: Commit**

```bash
git add src/repo_analyzer/inventory.py tests/test_inventory_generalized_discovery.py tests/test_parser_sql_init.py tests/test_compose_discovery.py
git commit -m "feat: discover SQL and Kubernetes files by pattern"
```

---

### Task 3: Classify SQL Scripts by Content

**Files:**
- Modify: `src/repo_analyzer/parsers/sql_init.py`
- Test: `tests/test_parser_sql_init.py`

**Interfaces:**
- Produces: `SqlInitScript.script_kind: Literal["schema", "data", "mixed", "unknown"]`
- Produces: `SqlInitScript.insert_table_names: list[Located]`
- Keeps: `table_names`, `has_create_tables`, `is_idempotent`

- [ ] **Step 1: Add failing SQL classification tests**

Append to `tests/test_parser_sql_init.py`:

```python
from repo_analyzer.parsers.sql_init import parse_sql_init


def test_classifies_nonstandard_schema_filename_by_create_table():
    script = parse_sql_init("CREATE TABLE orders (id int);\n", "database/init-v1.sql")

    assert script.script_kind == "schema"
    assert [t.value for t in script.table_names] == ["orders"]


def test_classifies_seed_script_by_insert_statements():
    script = parse_sql_init(
        "INSERT INTO account VALUES (1);\n"
        "insert into orders values (10);\n",
        "db/load-demo.sql",
    )

    assert script.script_kind == "data"
    assert [t.value for t in script.insert_table_names] == ["account", "orders"]


def test_classifies_mixed_schema_and_seed_file():
    script = parse_sql_init(
        "CREATE TABLE account (id int);\n"
        "INSERT INTO account VALUES (1);\n",
        "db/bootstrap.sql",
    )

    assert script.script_kind == "mixed"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_parser_sql_init.py
```

Expected: FAIL because `script_kind` and `insert_table_names` do not exist.

- [ ] **Step 3: Implement content classification**

In `src/repo_analyzer/parsers/sql_init.py`, add:

```python
from typing import Literal

SqlScriptKind = Literal["schema", "data", "mixed", "unknown"]

_INSERT_TABLE_NAME = re.compile(
    r"\binsert\s+into\s+(?P<name>(?:[`\"\[]?[\w$]+[`\"\]]?\.)?[`\"\[]?[\w$]+[`\"\]]?)",
    re.IGNORECASE,
)
```

Update `SqlInitScript`:

```python
    insert_table_names: list[Located] = field(default_factory=list)

    @property
    def script_kind(self) -> SqlScriptKind:
        has_schema = bool(self.table_names)
        has_data = bool(self.insert_table_names)
        if has_schema and has_data:
            return "mixed"
        if has_schema:
            return "schema"
        if has_data:
            return "data"
        return "unknown"
```

In `parse_sql_init()`, add after create table parsing:

```python
        insert_match = _INSERT_TABLE_NAME.search(raw)
        if insert_match:
            name = _normalise_table_name(insert_match.group("name"))
            if name:
                script.insert_table_names.append(
                    Located(value=name, selector=f"INSERT INTO {name}", start_line=line_no, end_line=line_no)
                )
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_parser_sql_init.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/parsers/sql_init.py tests/test_parser_sql_init.py
git commit -m "feat: classify SQL init scripts by content"
```

---

### Task 4: Parse Kubernetes YAML Manifests and Emit Manifest Findings

**Files:**
- Create: `src/repo_analyzer/parsers/kubernetes_yaml.py`
- Modify: `src/repo_analyzer/analyzer.py`
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_parser_kubernetes_yaml.py`
- Test: `tests/test_migration_questions.py`

**Interfaces:**
- Produces: `KubernetesManifest(path: str, resources: list[KubernetesResource], issues: list[str])`
- Produces: `KubernetesResource(api_version: Located, kind: Located, name: Located | None, ports: list[Located], env_names: list[Located], configmap_refs: list[Located], secret_refs: list[Located])`
- `analyze_kubernetes_p0()` receives `kubernetes_manifests: dict[str, KubernetesManifest]`
- Produces findings:
  - `networking`: `k8s.service_port.<name>`, `k8s.container_port.<name>`
  - `configuration`: `k8s.configmap_ref.<name>`
  - `secrets`: `k8s.secret_ref.<name>`
  - `workload_mappings`: existing manifest kind/name facts as explicit basis where useful
- Produces warning code `source_conflict` when K8s manifest port evidence disagrees with existing component/networking port evidence.

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_parser_kubernetes_yaml.py`:

```python
from repo_analyzer.parsers.kubernetes_yaml import parse_kubernetes_yaml


def test_parses_multi_document_kubernetes_yaml():
    manifest = parse_kubernetes_yaml(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api\n",
        "deploy/app.yaml",
    )

    assert [(r.kind.value, r.name.value) for r in manifest.resources] == [
        ("Deployment", "api"),
        ("Service", "api"),
    ]
    assert manifest.resources[0].kind.start_line == 2
    assert manifest.resources[1].kind.start_line == 7


def test_ignores_non_kubernetes_yaml_document():
    manifest = parse_kubernetes_yaml("feature: true\n", "config/settings.yaml")

    assert manifest.resources == []


def test_extracts_p0_ports_and_env_names():
    manifest = parse_kubernetes_yaml(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: api\n"
        "          ports:\n"
        "            - containerPort: 8080\n"
        "          env:\n"
        "            - name: SPRING_PROFILES_ACTIVE\n"
        "              valueFrom:\n"
        "                configMapKeyRef:\n"
        "                  name: app-config\n"
        "                  key: profile\n"
        "            - name: DB_PASSWORD\n"
        "              valueFrom:\n"
        "                secretKeyRef:\n"
        "                  name: db-secret\n"
        "                  key: password\n"
        "          envFrom:\n"
        "            - configMapRef:\n"
        "                name: shared-config\n"
        "            - secretRef:\n"
        "                name: shared-secret\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  ports:\n"
        "    - port: 80\n"
        "      targetPort: 8080\n",
        "deploy/app.yaml",
    )

    deployment, service = manifest.resources
    assert [p.value for p in deployment.ports] == [8080]
    assert [e.value for e in deployment.env_names] == ["SPRING_PROFILES_ACTIVE", "DB_PASSWORD"]
    assert [r.value for r in deployment.configmap_refs] == ["app-config", "shared-config"]
    assert [r.value for r in deployment.secret_refs] == ["db-secret", "shared-secret"]
    assert [p.value for p in service.ports] == [80, 8080]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_parser_kubernetes_yaml.py
```

Expected: FAIL because parser module does not exist.

- [ ] **Step 3: Implement parser**

Create `src/repo_analyzer/parsers/kubernetes_yaml.py`:

```python
"""Kubernetes YAML parser for manifest evidence.

This confirms Kubernetes documents and extracts only P0 evidence: apiVersion,
kind, and metadata.name with line numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ruamel.yaml import YAML

from .common import Located


@dataclass
class KubernetesResource:
    api_version: Located
    kind: Located
    name: Located | None = None
    ports: list[Located] = field(default_factory=list)
    env_names: list[Located] = field(default_factory=list)
    configmap_refs: list[Located] = field(default_factory=list)
    secret_refs: list[Located] = field(default_factory=list)


@dataclass
class KubernetesManifest:
    path: str
    resources: list[KubernetesResource] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def parse_kubernetes_yaml(text: str, path: str) -> KubernetesManifest:
    manifest = KubernetesManifest(path=path)
    yaml = YAML(typ="rt")
    try:
        docs = list(yaml.load_all(text))
    except Exception as exc:
        manifest.issues.append(f"yaml_parse_error: {exc}")
        return manifest

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        api_version = doc.get("apiVersion")
        kind = doc.get("kind")
        if not api_version or not kind:
            continue
        api_line = _line_for_key(doc, "apiVersion")
        kind_line = _line_for_key(doc, "kind")
        name = None
        metadata = doc.get("metadata")
        if isinstance(metadata, dict) and metadata.get("name"):
            name_line = _line_for_key(metadata, "name")
            name = Located(str(metadata.get("name")), "metadata.name", name_line, name_line)
        manifest.resources.append(
            KubernetesResource(
                api_version=Located(str(api_version), "apiVersion", api_line, api_line),
                kind=Located(str(kind), "kind", kind_line, kind_line),
                name=name,
                ports=_collect_ports(doc),
                env_names=_collect_env_names(doc),
                configmap_refs=_collect_named_refs(doc, "configMapRef", "configMapKeyRef"),
                secret_refs=_collect_named_refs(doc, "secretRef", "secretKeyRef"),
            )
        )
    return manifest


def _line_for_key(mapping: dict, key: str) -> int:
    try:
        return int(mapping.lc.key(key)[0]) + 1
    except Exception:
        return 1


def _collect_ports(node) -> list[Located]:
    ports: list[Located] = []
    if isinstance(node, dict):
        for key in ("port", "targetPort", "containerPort"):
            value = node.get(key)
            if isinstance(value, int):
                line = _line_for_key(node, key)
                ports.append(Located(value, key, line, line))
        for value in node.values():
            ports.extend(_collect_ports(value))
    elif isinstance(node, list):
        for item in node:
            ports.extend(_collect_ports(item))
    return ports


def _collect_env_names(node) -> list[Located]:
    names: list[Located] = []
    if isinstance(node, dict):
        if "env" in node and isinstance(node["env"], list):
            for item in node["env"]:
                if isinstance(item, dict) and item.get("name"):
                    line = _line_for_key(item, "name")
                    names.append(Located(str(item["name"]), "env.name", line, line))
        for value in node.values():
            names.extend(_collect_env_names(value))
    elif isinstance(node, list):
        for item in node:
            names.extend(_collect_env_names(item))
    return names


def _collect_named_refs(node, *keys: str) -> list[Located]:
    refs: list[Located] = []
    if isinstance(node, dict):
        for key in keys:
            ref = node.get(key)
            if isinstance(ref, dict) and ref.get("name"):
                line = _line_for_key(ref, "name")
                refs.append(Located(str(ref["name"]), f"{key}.name", line, line))
        for value in node.values():
            refs.extend(_collect_named_refs(value, *keys))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_named_refs(item, *keys))
    return refs
```

- [ ] **Step 4: Wire parser into analyzer**

In `analyzer.py`, import:

```python
from .parsers.kubernetes_yaml import KubernetesManifest, parse_kubernetes_yaml
```

After SQL parsing:

```python
    kubernetes_manifests: dict[str, KubernetesManifest] = {
        rel: parse_kubernetes_yaml(_read(root, rel), rel) for rel in inventory.kubernetes_yaml_files
    }
```

Pass `kubernetes_manifests=kubernetes_manifests` into `analyze_kubernetes_p0()`.

In `kubernetes_p0.py`, update the function signature:

```python
    kubernetes_manifests: dict[str, KubernetesManifest] | None = None,
```

Initialize:

```python
    kubernetes_manifests = kubernetes_manifests or {}
```

- [ ] **Step 5: Run parser tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_parser_kubernetes_yaml.py
```

Expected: PASS.

- [ ] **Step 6: Run analyzer smoke test**

Append to `tests/test_migration_questions.py`:

```python
def test_kubernetes_manifest_facts_are_emitted_as_findings(tmp_path):
    manifest = tmp_path / "k8s" / "app.yaml"
    manifest.parent.mkdir()
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: api\n"
        "          ports:\n"
        "            - containerPort: 8080\n"
        "          envFrom:\n"
        "            - configMapRef:\n"
        "                name: app-config\n"
        "            - secretRef:\n"
        "                name: app-secret\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  ports:\n"
        "    - port: 80\n"
        "      targetPort: 8080\n"
    )

    result = analyze_repository(str(tmp_path))

    assert any(f.subject == "k8s.container_port.api" for f in result.networking)
    assert any(f.subject == "k8s.service_port.api" for f in result.networking)
    assert any(f.subject == "k8s.configmap_ref.app-config" for f in result.configuration)
    assert any(f.subject == "k8s.secret_ref.app-secret" for f in result.secrets)
```

Add to `src/repo_analyzer/rules/kubernetes_p0.py`:

```python
def _emit_kubernetes_manifest_findings(
    result: AnalysisResult,
    kubernetes_manifests: dict[str, KubernetesManifest],
) -> None:
    for path, manifest in kubernetes_manifests.items():
        for resource in manifest.resources:
            name = resource.name.value if resource.name else "unnamed"
            if resource.kind.value == "Service":
                for port in resource.ports:
                    result.networking.append(
                        Finding(
                            subject=f"k8s.service_port.{name}",
                            value=port.value,
                            confidence="explicit",
                            kubernetes_effect="existing Kubernetes Service port evidence",
                            evidence=[Evidence(path=path, selector=port.selector, symbol="k8s.service.port", start_line=port.start_line, end_line=port.end_line)],
                        )
                    )
            if resource.kind.value in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}:
                for port in resource.ports:
                    result.networking.append(
                        Finding(
                            subject=f"k8s.container_port.{name}",
                            value=port.value,
                            confidence="explicit",
                            kubernetes_effect="existing Kubernetes workload container port evidence",
                            evidence=[Evidence(path=path, selector=port.selector, symbol="k8s.container.port", start_line=port.start_line, end_line=port.end_line)],
                        )
                    )
            for ref in resource.configmap_refs:
                result.configuration.append(
                    Finding(
                        subject=f"k8s.configmap_ref.{ref.value}",
                        value=ref.value,
                        confidence="explicit",
                        kubernetes_effect="existing Kubernetes ConfigMap reference",
                        evidence=[Evidence(path=path, selector=ref.selector, symbol="k8s.configmap_ref", start_line=ref.start_line, end_line=ref.end_line)],
                    )
                )
            for ref in resource.secret_refs:
                result.secrets.append(
                    Finding(
                        subject=f"k8s.secret_ref.{ref.value}",
                        value=ref.value,
                        confidence="explicit",
                        kubernetes_effect="existing Kubernetes Secret reference",
                        evidence=[Evidence(path=path, selector=ref.selector, symbol="k8s.secret_ref", start_line=ref.start_line, end_line=ref.end_line)],
                    )
                )
```

Call `_emit_kubernetes_manifest_findings(result, kubernetes_manifests)` after component/workload analysis and before `_emit_migration_questions(result)`.

Add a conflict helper:

```python
def _emit_source_conflict_warnings(result: AnalysisResult) -> None:
    component_ports = {port for component in result.components for port in component.container_ports}
    manifest_ports = {
        int(f.value)
        for f in result.networking
        if f.subject.startswith("k8s.container_port.") and isinstance(f.value, int)
    }
    if component_ports and manifest_ports and component_ports.isdisjoint(manifest_ports):
        result.warnings.append(
            Warning(
                code="source_conflict",
                message=(
                    "Kubernetes manifest container ports do not match component/container port evidence; "
                    f"component ports={sorted(component_ports)}, manifest ports={sorted(manifest_ports)}"
                ),
                path=None,
            )
        )
```

Call `_emit_source_conflict_warnings(result)` immediately after `_emit_kubernetes_manifest_findings(...)`.

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_determinism_and_errors.py::test_analysis_does_not_modify_target_repo
```

Expected: PASS.

- [ ] **Step 7: Run manifest integration test**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_kubernetes_manifest_facts_are_emitted_as_findings
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/repo_analyzer/parsers/kubernetes_yaml.py src/repo_analyzer/analyzer.py src/repo_analyzer/rules/kubernetes_p0.py tests/test_parser_kubernetes_yaml.py tests/test_migration_questions.py
git commit -m "feat: parse Kubernetes manifest evidence"
```

---

### Task 5: Emit Source Coverage Matrix

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_migration_questions.py`

**Interfaces:**
- Consumes: `Inventory`
- Consumes: `readmes: dict[str, list[str]]`
- Produces: `AnalysisResult.source_coverage`

- [ ] **Step 1: Write failing coverage tests**

Append to `tests/test_migration_questions.py`:

```python
from repo_analyzer.analyzer import analyze_repository


def test_source_coverage_records_present_missing_and_supplemental_sources(tmp_path):
    (tmp_path / "README.md").write_text("# Sample App\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:16\n")
    sql = tmp_path / "db" / "init.sql"
    sql.parent.mkdir()
    sql.write_text("CREATE TABLE account (id int);\n")

    result = analyze_repository(str(tmp_path))
    coverage = {c.source_class: c for c in result.source_coverage}

    assert coverage["readme"].status == "present"
    assert coverage["sql"].status == "present"
    assert coverage["compose"].status == "ignored"
    assert coverage["compose"].role == "sample_or_documented_deployment"
    assert coverage["dockerfile"].status == "missing"


def test_source_coverage_promotes_documented_compose_when_readme_selects_it(tmp_path):
    (tmp_path / "README.md").write_text("Run with `docker compose -f docs/docker-compose.yml up`.\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "docker-compose.yml").write_text("services:\n  app:\n    image: demo/app\n")

    result = analyze_repository(str(tmp_path))
    coverage = {c.source_class: c for c in result.source_coverage}

    assert coverage["compose"].status == "present"
    assert coverage["compose"].role == "selected_primary"
    assert coverage["compose"].paths == ["docs/docker-compose.yml"]


def test_source_coverage_records_large_candidate_gaps(tmp_path):
    sql = tmp_path / "db" / "huge.sql"
    sql.parent.mkdir()
    sql.write_text(" " * (10 * 1024 * 1024 + 1))

    result = analyze_repository(str(tmp_path))
    coverage = {c.source_class: c for c in result.source_coverage}

    assert coverage["skipped_large_candidates"].status == "error"
    assert coverage["skipped_large_candidates"].paths == ["db/huge.sql"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_source_coverage_records_present_missing_and_supplemental_sources
```

Expected: FAIL because `source_coverage` is empty.

- [ ] **Step 3: Implement coverage helper**

In `kubernetes_p0.py`, import `SourceCoverage` and add:

```python
def _emit_source_coverage(result: AnalysisResult, inventory: Inventory, readmes: dict[str, list[str]]) -> None:
    def add(source_class: str, paths: list[str], detection: str, role: str = "primary", status: str | None = None) -> None:
        resolved_status = status or ("present" if paths else "missing")
        result.source_coverage.append(
            SourceCoverage(
                source_class=source_class,
                status=resolved_status,
                paths=sorted(paths),
                role=role,
                detection=detection,
            )
        )

    compose_paths = []
    if inventory.compose_primary:
        compose_paths.append(inventory.compose_primary)
    compose_paths.extend(inventory.compose_extra)
    selected_ignored = [
        path for path in inventory.compose_ignored
        if _path_referenced_by_readme(path, readmes)
    ]
    if compose_paths:
        add("compose", compose_paths, "compose*.yml/yaml or docker-compose*.yml/yaml filename pattern")
    elif selected_ignored:
        add(
            "compose",
            selected_ignored,
            "compose file under documentation/example path selected by README reference",
            role="selected_primary",
            status="present",
        )
    elif inventory.compose_ignored:
        add(
            "compose",
            inventory.compose_ignored,
            "compose filename pattern under documentation/example/test path",
            role="sample_or_documented_deployment",
            status="ignored",
        )
    else:
        add("compose", [], "compose filename pattern")

    add("dockerfile", inventory.dockerfiles, "Dockerfile, Dockerfile.*, or *.Dockerfile filename pattern")
    add("app_config", inventory.spring_property_files + inventory.spring_yaml_files, "application*.properties/yml/yaml filename pattern")
    add("sql", inventory.sql_init_files, ".sql extension plus SQL parser classification")
    add("kubernetes", inventory.kubernetes_yaml_files, "YAML apiVersion/kind content sniff")
    if inventory.skipped_large_candidates:
        add(
            "skipped_large_candidates",
            inventory.skipped_large_candidates,
            "candidate exceeded 10 MiB parse limit",
            role="supplemental",
            status="error",
        )
    add("web_xml", inventory.web_descriptors, "web.xml filename")
    add("build_file", inventory.maven_files + inventory.gradle_files, "pom.xml or build.gradle(.kts)")
    add("readme", inventory.readme_files, "README* filename")


def _path_referenced_by_readme(path: str, readmes: dict[str, list[str]]) -> bool:
    for lines in readmes.values():
        if any(path in line for line in lines):
            return True
    return False
```

Call `_emit_source_coverage(result, inventory, readmes)` immediately after `AnalysisResult(...)` construction in `analyze_kubernetes_p0()`.

- [ ] **Step 4: Run test and verify it passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_source_coverage_records_present_missing_and_supplemental_sources
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/repo_analyzer/rules/kubernetes_p0.py tests/test_migration_questions.py
git commit -m "feat: report repository source coverage"
```

---

### Task 6: Build Seven Evidence-Backed Migration Questions

**Files:**
- Modify: `src/repo_analyzer/rules/kubernetes_p0.py`
- Test: `tests/test_migration_questions.py`
- Test: `tests/test_golden_jpetstore.py`

**Interfaces:**
- Produces seven `MigrationQuestionAnswer` entries with IDs:
  - `application_identity`
  - `build_and_run`
  - `ports_and_services`
  - `external_dependencies`
  - `configmaps_and_secrets`
  - `persistent_data`
  - `repository_unknowns`

- [ ] **Step 1: Write failing seven-question structural test**

Append to `tests/test_migration_questions.py`:

```python
def test_migration_questions_are_always_emitted_with_basis_or_missing(jpetstore_repo):
    result = analyze_repository(str(jpetstore_repo))

    expected_ids = [
        "application_identity",
        "build_and_run",
        "ports_and_services",
        "external_dependencies",
        "configmaps_and_secrets",
        "persistent_data",
        "repository_unknowns",
    ]
    assert [q.id for q in result.migration_questions] == expected_ids

    for question in result.migration_questions:
        assert question.question
        assert question.answer
        assert question.status in {"answered", "partial", "unresolved", "not_detected"}
        assert question.basis or question.missing


def test_persistent_data_question_does_not_treat_empty_app_storage_as_no_data(jpetstore_repo):
    result = analyze_repository(str(jpetstore_repo))
    persistent = next(q for q in result.migration_questions if q.id == "persistent_data")

    assert persistent.status == "partial"
    assert "embedded HSQL" in persistent.answer
    assert "application PVC" in persistent.answer
    assert any("external database" in item.lower() for item in persistent.missing)


def test_kubernetes_manifest_findings_are_used_as_question_basis(tmp_path):
    manifest = tmp_path / "k8s" / "app.yaml"
    manifest.parent.mkdir()
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: api\n"
        "          ports:\n"
        "            - containerPort: 8080\n"
        "          envFrom:\n"
        "            - configMapRef:\n"
        "                name: app-config\n"
        "            - secretRef:\n"
        "                name: app-secret\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  ports:\n"
        "    - port: 80\n"
        "      targetPort: 8080\n"
    )

    result = analyze_repository(str(tmp_path))
    questions = {q.id: q for q in result.migration_questions}

    assert any(b.source_section == "networking" for b in questions["ports_and_services"].basis)
    assert any(b.source_section == "configuration" for b in questions["configmaps_and_secrets"].basis)
    assert any(b.source_section == "secrets" for b in questions["configmaps_and_secrets"].basis)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_migration_questions_are_always_emitted_with_basis_or_missing tests/test_migration_questions.py::test_persistent_data_question_does_not_treat_empty_app_storage_as_no_data
```

Expected: FAIL because no migration questions are emitted.

- [ ] **Step 3: Implement basis helpers**

In `kubernetes_p0.py`, import `AnswerBasis` and `MigrationQuestionAnswer`, then add:

```python
_MIGRATION_QUESTIONS = [
    ("application_identity", "어떤 애플리케이션인가?"),
    ("build_and_run", "어떻게 빌드하고 실행하는가?"),
    ("ports_and_services", "어떤 Port와 Service가 필요한가?"),
    ("external_dependencies", "어떤 외부 의존성이 있는가?"),
    ("configmaps_and_secrets", "어떤 ConfigMap과 Secret이 필요한가?"),
    ("persistent_data", "어떤 데이터가 영속되어야 하는가?"),
    ("repository_unknowns", "Repository만으로 결정할 수 없는 값은 무엇인가?"),
]


def _basis(source_section: str, subject: str, evidence: list[Evidence] | None = None) -> AnswerBasis:
    return AnswerBasis(source_section=source_section, subject=subject, evidence=evidence or [])
```

- [ ] **Step 4: Implement question builder**

Add:

```python
def _emit_migration_questions(result: AnalysisResult) -> None:
    result.migration_questions = [
        _question_application_identity(result),
        _question_build_and_run(result),
        _question_ports_and_services(result),
        _question_external_dependencies(result),
        _question_configmaps_and_secrets(result),
        _question_persistent_data(result),
        _question_repository_unknowns(result),
    ]
```

Call `_emit_migration_questions(result)` at the end of `analyze_kubernetes_p0()` immediately before `return result`.

Add these implementations:

```python
def _question_application_identity(result: AnalysisResult) -> MigrationQuestionAnswer:
    components = [c for c in result.components]
    if not components:
        return MigrationQuestionAnswer(
            id="application_identity",
            question=_MIGRATION_QUESTIONS[0][1],
            status="not_detected",
            answer="No deployable application component was detected from repository facts.",
            missing=["deployable build file, Dockerfile, Compose service, or web application descriptor"],
        )
    summary = "; ".join(
        f"{c.name}: {c.runtime or c.language or 'runtime not detected'}"
        for c in components
    )
    return MigrationQuestionAnswer(
        id="application_identity",
        question=_MIGRATION_QUESTIONS[0][1],
        status="answered" if any(c.runtime or c.language for c in components) else "partial",
        answer=summary,
        basis=[_basis("components", c.name) for c in components],
        missing=[] if any(c.runtime or c.language for c in components) else ["application runtime/framework summary"],
    )


def _question_build_and_run(result: AnalysisResult) -> MigrationQuestionAnswer:
    basis = []
    parts = []
    missing = []
    for c in result.components:
        if c.build_tool or c.build_command or c.command or c.dockerfile:
            bits = [c.name]
            if c.build_tool:
                bits.append(c.build_tool)
            if c.build_command:
                bits.append(f"build `{c.build_command}`")
            if c.command:
                bits.append(f"run `{' '.join(c.command)}`")
            if c.dockerfile:
                bits.append(f"Dockerfile `{c.dockerfile}`")
            parts.append(": ".join([bits[0], ", ".join(bits[1:])]))
            basis.append(_basis("components", c.name))
        else:
            missing.append(f"{c.name} build/run command")
    status = "answered" if parts and not missing else ("partial" if parts else "unresolved")
    return MigrationQuestionAnswer(
        id="build_and_run",
        question=_MIGRATION_QUESTIONS[1][1],
        status=status,
        answer="; ".join(parts) if parts else "Build and run commands were not detected.",
        basis=basis,
        missing=missing or [],
    )


def _question_ports_and_services(result: AnalysisResult) -> MigrationQuestionAnswer:
    port_findings = [f for f in result.networking if "port" in f.subject.lower() or "context_path" in f.subject]
    workload_basis = [_basis("workload_mappings", w.component, w.evidence) for w in result.workload_mappings]
    parts = []
    for c in result.components:
        if c.container_ports:
            parts.append(f"{c.name} targetPort {', '.join(str(p) for p in c.container_ports)}")
    if result.workload_mappings:
        parts.append("; ".join(f"{w.component} -> {w.kubernetes_kind}" for w in result.workload_mappings))
    missing = []
    if not parts:
        missing.append("container port or Service targetPort")
    status = "answered" if parts and not missing else ("partial" if parts else "unresolved")
    return MigrationQuestionAnswer(
        id="ports_and_services",
        question=_MIGRATION_QUESTIONS[2][1],
        status=status,
        answer="; ".join(parts) if parts else "No port or Service candidate was detected.",
        basis=[_basis("networking", f.subject, f.evidence) for f in port_findings] + workload_basis,
        missing=missing,
    )


def _question_external_dependencies(result: AnalysisResult) -> MigrationQuestionAnswer:
    if not result.runtime_dependencies:
        return MigrationQuestionAnswer(
            id="external_dependencies",
            question=_MIGRATION_QUESTIONS[3][1],
            status="not_detected",
            answer="No external runtime dependency was detected.",
            missing=["external service evidence may still be absent from scanned file classes"],
        )
    return MigrationQuestionAnswer(
        id="external_dependencies",
        question=_MIGRATION_QUESTIONS[3][1],
        status="answered",
        answer="; ".join(f"{f.subject}: {f.value}" for f in result.runtime_dependencies),
        basis=[_basis("runtime_dependencies", f.subject, f.evidence) for f in result.runtime_dependencies],
    )


def _question_configmaps_and_secrets(result: AnalysisResult) -> MigrationQuestionAnswer:
    config = [
        f for f in result.configuration
        if "ConfigMap key candidate" in f.kubernetes_effect
        or f.subject.startswith("k8s.configmap_ref.")
    ]
    secrets = result.secrets
    if not config and not secrets:
        return MigrationQuestionAnswer(
            id="configmaps_and_secrets",
            question=_MIGRATION_QUESTIONS[4][1],
            status="not_detected",
            answer="No ConfigMap or Secret candidates were detected.",
            missing=[],
        )
    return MigrationQuestionAnswer(
        id="configmaps_and_secrets",
        question=_MIGRATION_QUESTIONS[4][1],
        status="answered",
        answer=f"ConfigMap candidates: {len(config)}; Secret candidates: {len(secrets)}",
        basis=[_basis("configuration", f.subject, f.evidence) for f in config]
        + [_basis("secrets", f.subject, f.evidence) for f in secrets],
    )


def _question_persistent_data(result: AnalysisResult) -> MigrationQuestionAnswer:
    db_deps = [f for f in result.runtime_dependencies if "database" in f.subject.lower()]
    basis = [_basis("storage", f.subject, f.evidence) for f in result.storage]
    basis += [_basis("runtime_dependencies", f.subject, f.evidence) for f in db_deps]
    if result.storage:
        answer = "; ".join(f"{f.subject}: {f.value}" for f in result.storage)
        return MigrationQuestionAnswer(
            id="persistent_data",
            question=_MIGRATION_QUESTIONS[5][1],
            status="answered",
            answer=answer,
            basis=basis,
        )
    if db_deps:
        answer = "No application PVC was detected. Database state exists or is implied by runtime dependency: " + "; ".join(
            f"{f.subject}: {f.value}" for f in db_deps
        )
        return MigrationQuestionAnswer(
            id="persistent_data",
            question=_MIGRATION_QUESTIONS[5][1],
            status="partial",
            answer=answer,
            basis=basis,
            missing=["external database persistence decision or managed database policy"],
        )
    return MigrationQuestionAnswer(
        id="persistent_data",
        question=_MIGRATION_QUESTIONS[5][1],
        status="not_detected",
        answer="No application volume, database, or SQL persistence evidence was detected.",
        missing=["persistence evidence may be absent from scanned file classes"],
    )


def _question_repository_unknowns(result: AnalysisResult) -> MigrationQuestionAnswer:
    if not result.unresolved_operational_inputs:
        return MigrationQuestionAnswer(
            id="repository_unknowns",
            question=_MIGRATION_QUESTIONS[6][1],
            status="answered",
            answer="No unresolved operational input was recorded.",
            basis=[],
        )
    return MigrationQuestionAnswer(
        id="repository_unknowns",
        question=_MIGRATION_QUESTIONS[6][1],
        status="answered",
        answer="; ".join(u.subject for u in result.unresolved_operational_inputs),
        basis=[_basis("unresolved_operational_inputs", u.subject) for u in result.unresolved_operational_inputs],
        missing=[u.needed_input for u in result.unresolved_operational_inputs],
    )
```

- [ ] **Step 5: Run the failing tests again**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py
```

Expected: PASS.

- [ ] **Step 6: Add JPetStore golden guard**

Append to `tests/test_golden_jpetstore.py`:

```python
def test_seven_migration_questions_are_evidence_backed(result):
    questions = {q.id: q for q in result.migration_questions}
    assert questions["application_identity"].basis
    assert questions["build_and_run"].basis
    assert questions["ports_and_services"].basis
    assert questions["external_dependencies"].basis
    assert questions["persistent_data"].status == "partial"
    assert "embedded HSQL" in questions["persistent_data"].answer
    assert questions["repository_unknowns"].missing
```

- [ ] **Step 7: Run JPetStore tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_jpetstore.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/repo_analyzer/rules/kubernetes_p0.py tests/test_migration_questions.py tests/test_golden_jpetstore.py
git commit -m "feat: emit evidence-backed migration questions"
```

---

### Task 7: Render Migration Questions in Markdown

**Files:**
- Modify: `src/repo_analyzer/reporters/markdown_reporter.py`
- Test: `tests/test_migration_questions.py`

**Interfaces:**
- Consumes: `AnalysisResult.migration_questions`
- Replaces: old `## Quick answers` section with `## Migration questions`

- [ ] **Step 1: Write failing Markdown reporter test**

Append to `tests/test_migration_questions.py`:

```python
from repo_analyzer.reporters.markdown_reporter import to_markdown


def test_markdown_renders_migration_questions_with_status_basis_and_missing(jpetstore_repo):
    result = analyze_repository(str(jpetstore_repo))
    report = to_markdown(result)

    assert "## Migration questions" in report
    assert "## Quick answers" not in report
    assert "1. **어떤 애플리케이션인가?**" in report
    assert "- Status: `partial`" in report or "- Status: `answered`" in report
    assert "- Basis:" in report
    assert "- Missing:" in report
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_markdown_renders_migration_questions_with_status_basis_and_missing
```

Expected: FAIL because the reporter still renders `Quick answers`.

- [ ] **Step 3: Replace quick answers renderer**

In `to_markdown()`, replace:

```python
    _quick_answers_section(out, result)
```

with:

```python
    _migration_questions_section(out, result)
```

Replace `_quick_answers_section()` with:

```python
def _migration_questions_section(out, result: AnalysisResult) -> None:
    out("## Migration questions")
    out("")
    if not result.migration_questions:
        out("_No migration question answers emitted._")
        out("")
        return
    for index, q in enumerate(result.migration_questions, start=1):
        out(f"{index}. **{q.question}**")
        out(f"   - Status: `{q.status}`")
        out(f"   - Answer: {q.answer}")
        if q.basis:
            basis = "; ".join(
                f"{b.source_section}.{b.subject}"
                + (f" ({_fmt_evidence(b.evidence)})" if b.evidence else "")
                for b in q.basis
            )
            out(f"   - Basis: {basis}")
        else:
            out("   - Basis: —")
        if q.missing:
            out(f"   - Missing: {'; '.join(q.missing)}")
        else:
            out("   - Missing: —")
    out("")
```

- [ ] **Step 4: Run reporter test**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_migration_questions.py::test_markdown_renders_migration_questions_with_status_basis_and_missing
```

Expected: PASS.

- [ ] **Step 5: Run reporter/golden tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_jpetstore.py tests/test_golden_spring_petclinic.py
```

Expected: PASS after updating any expected Markdown assertions that referenced `Quick answers`.

- [ ] **Step 6: Commit**

```bash
git add src/repo_analyzer/reporters/markdown_reporter.py tests/test_migration_questions.py tests/test_golden_jpetstore.py tests/test_golden_spring_petclinic.py
git commit -m "feat: render migration questions in reports"
```

---

### Task 8: Regenerate Examples and Run Final Verification

**Files:**
- Modify: `examples/jpetstore-analysis.json`
- Modify: `examples/jpetstore-report.md`
- Modify: `examples/spring-petclinic-analysis.json`
- Modify: `examples/spring-petclinic-report.md`

**Interfaces:**
- Uses the existing CLI shape from `src/repo_analyzer/cli.py`: `repo-analyzer analyze --repo PATH --json-output PATH --markdown-output PATH`.

- [ ] **Step 1: Inspect CLI usage**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer analyze --help
```

Expected: CLI help prints `--repo`, `--build-system`, `--json-output`, and `--markdown-output`.

- [ ] **Step 2: Regenerate JPetStore JSON**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer analyze --repo tests/fixtures/jpetstore-6 --json-output examples/jpetstore-analysis.json
```

Expected: `examples/jpetstore-analysis.json` includes `source_coverage` and seven `migration_questions`.

- [ ] **Step 3: Regenerate JPetStore Markdown**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer analyze --repo tests/fixtures/jpetstore-6 --markdown-output examples/jpetstore-report.md
```

Expected: `examples/jpetstore-report.md` includes `## Migration questions`.

- [ ] **Step 4: Regenerate Spring PetClinic JSON**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer analyze --repo tests/fixtures/spring-petclinic --build-system gradle --json-output examples/spring-petclinic-analysis.json
```

Expected: `examples/spring-petclinic-analysis.json` includes source coverage for app config, SQL, Compose, K8s, build files, and README.

- [ ] **Step 5: Regenerate Spring PetClinic Markdown**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run repo-analyzer analyze --repo tests/fixtures/spring-petclinic --build-system gradle --markdown-output examples/spring-petclinic-report.md
```

Expected: `examples/spring-petclinic-report.md` includes the seven migration questions.

- [ ] **Step 6: Run full test suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Check deterministic output**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_golden_jpetstore.py::test_analysis_is_byte_deterministic
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add examples/jpetstore-analysis.json examples/jpetstore-report.md examples/spring-petclinic-analysis.json examples/spring-petclinic-report.md
git commit -m "test: update migration question examples"
```

---

### Task 9: Validate Against the Required 10 External Repositories

**Files:**
- Create: `scripts/validate_external_repos.py`
- Create: `docs/validation/2026-07-20-required-java-repos.md`
- Test: `tests/test_external_validation_script.py`

**Interfaces:**
- Produces CLI: `python scripts/validate_external_repos.py --workdir /tmp/repo-analyzer-validation --output docs/validation/2026-07-20-required-java-repos.md`
- Produces Markdown sections for exactly these repositories:
  - `mybatis/jpetstore-6`
  - `spring-projects/spring-petclinic`
  - `jhipster/jhipster-sample-app`
  - `macrozheng/mall`
  - `jeecgboot/JeecgBoot`
  - `apache/guacamole-client`
  - `apache/ofbiz-framework`
  - `openmrs/openmrs-core`
  - `shopizer-ecommerce/shopizer`
  - `halo-dev/halo`
- Success criteria: each repository analysis completes, records the analyzed commit SHA, emits seven `migration_questions`, emits non-empty `source_coverage`, every question has either `basis` or `missing`, and the report includes at least two representative evidence samples per repository.

- [ ] **Step 1: Write failing validation script tests**

Create `tests/test_external_validation_script.py`:

```python
import importlib.util
from pathlib import Path


def _load_script():
    path = Path("scripts/validate_external_repos.py")
    spec = importlib.util.spec_from_file_location("validate_external_repos", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_required_repositories_are_exactly_the_validation_set():
    module = _load_script()

    assert module.REQUIRED_REPOSITORIES == [
        "mybatis/jpetstore-6",
        "spring-projects/spring-petclinic",
        "jhipster/jhipster-sample-app",
        "macrozheng/mall",
        "jeecgboot/JeecgBoot",
        "apache/guacamole-client",
        "apache/ofbiz-framework",
        "openmrs/openmrs-core",
        "shopizer-ecommerce/shopizer",
        "halo-dev/halo",
    ]


def test_validate_result_requires_seven_questions_coverage_and_evidence_samples():
    module = _load_script()

    class Evidence:
        path = "pom.xml"
        start_line = 10
        end_line = 12

    class Basis:
        source_section = "configuration"
        subject = "build.tool"
        evidence = [Evidence()]

    class Question:
        def __init__(self, missing):
            self.basis = [Basis()]
            self.missing = missing

    class Result:
        source_coverage = ["coverage"]
        migration_questions = [Question([]) for _ in range(7)]

    assert module.validate_result("owner/repo", Result()) == []


def test_validate_result_reports_missing_basis_or_missing():
    module = _load_script()

    class Question:
        basis = []
        missing = []

    class Result:
        source_coverage = []
        migration_questions = [Question()]

    errors = module.validate_result("owner/repo", Result())

    assert "expected 7 migration questions, got 1" in errors
    assert "source_coverage is empty" in errors
    assert "question 1 has neither basis nor missing" in errors


def test_validate_result_requires_two_evidence_samples():
    module = _load_script()

    class Question:
        basis = []
        missing = ["missing input"]

    class Result:
        source_coverage = ["coverage"]
        migration_questions = [Question() for _ in range(7)]

    errors = module.validate_result("owner/repo", Result())

    assert "expected at least 2 representative evidence samples, got 0" in errors


def test_render_repo_row_includes_commit_sha_and_evidence_samples():
    module = _load_script()

    class Evidence:
        path = "pom.xml"
        start_line = 10
        end_line = 12

    class Basis:
        source_section = "configuration"
        subject = "build.tool"
        evidence = [Evidence()]

    class Question:
        id = "build_and_run"
        status = "answered"
        basis = [Basis()]
        missing = []

    class Coverage:
        source_class = "build_file"
        status = "present"

    class Result:
        source_coverage = [Coverage()]
        migration_questions = [Question()]

    row = module.render_repo_row("owner/repo", "abc1234", Result(), [])

    assert "`abc1234`" in row
    assert "configuration.build.tool @ pom.xml:10-12" in row


def test_render_repo_row_reports_warnings_without_failing():
    module = _load_script()

    class Warning:
        code = "source_conflict"

    class Coverage:
        source_class = "skipped_large_candidates"
        status = "error"

    class Result:
        warnings = [Warning()]
        source_coverage = [Coverage()]
        migration_questions = []

    row = module.render_repo_row("owner/repo", "abc1234", Result(), [])

    assert "| PASS |" in row
    assert "warnings: source_conflict" in row
    assert "coverage gaps: skipped_large_candidates" in row
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_external_validation_script.py
```

Expected: FAIL because `scripts/validate_external_repos.py` does not exist.

- [ ] **Step 3: Implement the validation script**

Create `scripts/validate_external_repos.py`:

```python
"""Validate migration question output against the required external Java repos."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from repo_analyzer.analyzer import analyze_repository

REQUIRED_REPOSITORIES = [
    "mybatis/jpetstore-6",
    "spring-projects/spring-petclinic",
    "jhipster/jhipster-sample-app",
    "macrozheng/mall",
    "jeecgboot/JeecgBoot",
    "apache/guacamole-client",
    "apache/ofbiz-framework",
    "openmrs/openmrs-core",
    "shopizer-ecommerce/shopizer",
    "halo-dev/halo",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default="/tmp/repo-analyzer-validation")
    parser.add_argument("--output", default="docs/validation/2026-07-20-required-java-repos.md")
    parser.add_argument("--skip-clone", action="store_true")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    output = Path(args.output)
    workdir.mkdir(parents=True, exist_ok=True)
    rows = []
    failures = []

    for repo in REQUIRED_REPOSITORIES:
        repo_dir = workdir / repo.replace("/", "__")
        if not args.skip_clone:
            clone_or_update(repo, repo_dir)
        commit_sha = current_commit(repo_dir)
        result = analyze_repository(str(repo_dir))
        errors = validate_result(repo, result)
        if errors:
            failures.append((repo, errors))
        rows.append(render_repo_row(repo, commit_sha, result, errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(rows, failures), encoding="utf-8")
    return 1 if failures else 0


def clone_or_update(repo: str, repo_dir: Path) -> None:
    url = f"https://github.com/{repo}.git"
    if repo_dir.exists():
        subprocess.run(["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin"], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "reset", "--hard", "FETCH_HEAD"], check=True)
        return
    subprocess.run(["git", "clone", "--depth", "1", url, str(repo_dir)], check=True)


def current_commit(repo_dir: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def validate_result(repo: str, result) -> list[str]:
    errors = []
    if len(result.migration_questions) != 7:
        errors.append(f"expected 7 migration questions, got {len(result.migration_questions)}")
    if not result.source_coverage:
        errors.append("source_coverage is empty")
    for index, question in enumerate(result.migration_questions, start=1):
        if not question.basis and not question.missing:
            errors.append(f"question {index} has neither basis nor missing")
    evidence_count = len(representative_evidence(result, limit=3))
    if evidence_count < 2:
        errors.append(f"expected at least 2 representative evidence samples, got {evidence_count}")
    return errors


def representative_evidence(result, limit: int = 3) -> list[str]:
    samples = []
    for question in result.migration_questions:
        for basis in question.basis:
            if not basis.evidence:
                continue
            evidence = basis.evidence[0]
            samples.append(
                f"{basis.source_section}.{basis.subject} @ "
                f"{evidence.path}:{evidence.start_line}-{evidence.end_line}"
            )
            if len(samples) >= limit:
                return samples
    return samples


def render_repo_row(repo: str, commit_sha: str, result, errors: list[str]) -> str:
    statuses = ", ".join(f"{q.id}={q.status}" for q in result.migration_questions)
    coverage = ", ".join(f"{c.source_class}:{c.status}" for c in result.source_coverage)
    warning_codes = ", ".join(w.code for w in getattr(result, "warnings", [])) or "none"
    coverage_gaps = ", ".join(
        c.source_class for c in result.source_coverage if c.status in {"error", "ignored", "missing"}
    ) or "none"
    samples = "; ".join(representative_evidence(result)) or "no line-located evidence samples"
    outcome = "PASS" if not errors else "FAIL: " + "; ".join(errors)
    return (
        f"| `{repo}` | `{commit_sha[:12]}` | {outcome} | {statuses} | {coverage} | "
        f"warnings: {warning_codes}; coverage gaps: {coverage_gaps} | {samples} |"
    )


def render_report(rows: list[str], failures: list[tuple[str, list[str]]]) -> str:
    lines = [
        "# Required Java Repository Validation",
        "",
        "Validation set is fixed by requirement and must contain exactly 10 repositories.",
        "",
        "| Repository | Commit | Outcome | Question statuses | Source coverage | Warnings/gaps | Evidence samples |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for repo, errors in failures:
            lines.append(f"- `{repo}`: {'; '.join(errors)}")
        lines.append("")
    else:
        lines.append("All required repositories passed structural validation with representative evidence samples.")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run validation script tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_external_validation_script.py
```

Expected: PASS.

- [ ] **Step 5: Run required external validation**

This command needs network access for GitHub clones unless the repositories already exist under `/tmp/repo-analyzer-validation`.

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run python scripts/validate_external_repos.py --workdir /tmp/repo-analyzer-validation --output docs/validation/2026-07-20-required-java-repos.md
```

Expected: command exits 0 and writes `docs/validation/2026-07-20-required-java-repos.md`.

- [ ] **Step 6: Inspect validation report**

Run:

```bash
sed -n '1,220p' docs/validation/2026-07-20-required-java-repos.md
```

Expected: the report contains exactly 10 rows, every row has outcome `PASS`, every row has a commit SHA, each row has 2-3 representative evidence samples when line-located evidence exists, and warnings/coverage gaps are visible without failing validation.

- [ ] **Step 7: Run full test suite after external validation**

Run:

```bash
UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/validate_external_repos.py tests/test_external_validation_script.py docs/validation/2026-07-20-required-java-repos.md
git commit -m "test: validate migration questions on required Java repos"
```

---

## Self-Review

Spec coverage:
- Generalized discovery: Task 2.
- SQL content classification: Task 3.
- K8s content classification and parsing: Task 4.
- Coverage matrix: Task 5.
- Deterministic seven-question answers: Task 6.
- Markdown report replacement: Task 7.
- Example regeneration and full verification: Task 8.
- Mandatory 10-repository validation: Task 9.
- Commit SHA recording and representative evidence samples for external validation: Task 9.

Placeholder scan:
- The plan contains no `TBD`, `TODO`, or unspecified implementation task.
- The only conditional command note is in Task 8 because CLI flags must be confirmed from the actual CLI help before regeneration.
- The validation repository set is explicit and fixed.
- External validation is not structure-only; it records commit SHA and evidence samples.
- Source conflicts and skipped large candidates are visible in validation output but are non-fatal.

Type consistency:
- `SourceCoverage`, `AnswerBasis`, and `MigrationQuestionAnswer` are defined in Task 1 and reused consistently.
- `KubernetesManifest` and `KubernetesResource` are defined in Task 4 before analyzer/rule use.
- `script_kind` and `insert_table_names` are defined in Task 3 before downstream rule use.
- `validate_result()` is defined in Task 9 before script tests and external validation use it.
