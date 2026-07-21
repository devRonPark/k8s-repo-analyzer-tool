"""Golden integration tests for the spring-petclinic (Gradle) fixture.

Rather than snapshotting the whole report, these assert the specific structural
facts a Kubernetes migration needs. The final block compares the source-derived
analysis against the repository's own ``k8s/`` manifests (ground truth, never
consumed by the analyzer) and uses any difference as a regression signal.
"""

from __future__ import annotations

import hashlib
import shutil

from repo_analyzer.analyzer import analyze_repository


def _config(result, subject):
    return next((f for f in result.configuration if f.subject == subject), None)


def _in_section(result, section, subject):
    return next((f for f in getattr(result, section) if f.subject == subject), None)


def _app(result):
    return next(c for c in result.components if c.name == "spring-petclinic")


# --------------------------------------------------------------------------- #
# Build system
# --------------------------------------------------------------------------- #
def test_build_system_is_gradle_and_lists_both(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _config(result, "build.system").value == "gradle"
    selection = _config(result, "build.system.selection").value
    assert selection["detected"] == ["gradle", "maven"]
    assert selection["selected"] == "gradle"
    assert "maven" in selection["how_to_select_other"]


def test_auto_selection_also_picks_gradle(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo))
    assert _config(result, "build.system").value == "gradle"
    assert any(w.code == "multiple_build_systems" for w in result.warnings)


# --------------------------------------------------------------------------- #
# Java / Spring Boot / build artifact
# --------------------------------------------------------------------------- #
def test_java_toolchain_and_spring_boot_version(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _app(result).language == "Java 17"
    assert _config(result, "runtime.java_version").value == "Java 17"
    assert _config(result, "framework.spring_boot").value == "4.1.0"


def test_gradle_wrapper_and_tasks(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _config(result, "build.wrapper").value == "./gradlew"
    assert _config(result, "build.command.bootjar").value == "./gradlew clean bootJar"
    assert _config(result, "build.command.bootrun").value == "./gradlew bootRun"
    assert _config(result, "build.command.test").value == "./gradlew test"


def test_readme_run_commands_are_available_without_switching_build_system(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    subjects = {f.subject: f for f in result.configuration}
    assert subjects["build.system"].value == "gradle"
    assert subjects["run.command.gradle"].value == "./gradlew bootRun"
    assert subjects["run.command.maven"].value == "./mvnw spring-boot:run"
    assert subjects["image.build_command.maven"].value == "./mvnw spring-boot:build-image"


def test_executable_jar_artifact(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _config(result, "build.artifact_type").value == "executable-jar"
    app = _app(result)
    assert app.build_artifact == "build/libs/spring-petclinic-4.0.0-SNAPSHOT.jar"
    assert app.build_artifact.startswith("build/libs/") and app.build_artifact.endswith(".jar")
    assert _config(result, "runtime.exec_command").value.startswith("java -jar build/libs/")


# --------------------------------------------------------------------------- #
# Networking / port
# --------------------------------------------------------------------------- #
def test_default_port_8080_with_evidence(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    port = _in_section(result, "networking", "app.default_port")
    assert port.value == 8080
    assert port.confidence == "derived"
    assert port.evidence  # web starter + README corroboration
    assert _in_section(result, "networking", "service.target_port").value == 8080
    assert _app(result).container_ports == [8080]


def test_service_exposure_is_unresolved_not_guessed(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    subjects = {u.subject for u in result.unresolved_operational_inputs}
    assert "service_port_and_type" in subjects


def test_app_service_candidate_separates_target_port_from_operational_exposure(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    service = _in_section(result, "networking", "service.app")
    assert service.value == {
        "kind": "Service",
        "target_port": 8080,
        "port": "unresolved",
        "type": "unresolved",
    }
    assert service.confidence == "derived"


# --------------------------------------------------------------------------- #
# Database profiles & env classification
# --------------------------------------------------------------------------- #
def test_h2_default_not_recommended_for_production(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    default_db = _in_section(result, "runtime_dependencies", "database.default")
    assert "h2" in default_db.value.lower()
    assert "production" in default_db.kubernetes_effect.lower()


def test_postgres_and_mysql_profiles_distinguished(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "runtime_dependencies", "database.profile.postgres") is not None
    assert _in_section(result, "runtime_dependencies", "database.profile.mysql") is not None


def test_required_env_classified_configmap_vs_secret(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    pg = _config(result, "profile.postgres.required_env").value
    my = _config(result, "profile.mysql.required_env").value
    assert pg == ["POSTGRES_URL", "POSTGRES_USER", "POSTGRES_PASS"]
    assert my == ["MYSQL_URL", "MYSQL_USER", "MYSQL_PASS"]
    secret_subjects = {f.subject for f in result.secrets}
    assert "secret.POSTGRES_PASS" in secret_subjects
    assert "secret.MYSQL_PASS" in secret_subjects
    # URLs are ConfigMap candidates, never secrets.
    assert "secret.POSTGRES_URL" not in secret_subjects
    assert _config(result, "config.POSTGRES_URL") is not None
    app = _app(result)
    assert "POSTGRES_PASS" in app.secret_candidates
    assert "POSTGRES_URL" in app.environment and "POSTGRES_URL" not in app.secret_candidates


def test_profile_kubernetes_inputs_group_configmap_and_secret_keys(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    pg = _config(result, "profile.postgres.kubernetes_inputs")
    assert pg.value == {
        "configmap_keys": ["SPRING_PROFILES_ACTIVE", "POSTGRES_URL"],
        "secret_keys": ["POSTGRES_USER", "POSTGRES_PASS"],
    }
    profile = _config(result, "config.SPRING_PROFILES_ACTIVE")
    assert "ConfigMap key candidate" in profile.kubernetes_effect


def test_production_database_selection_is_unresolved(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    subjects = {u.subject for u in result.unresolved_operational_inputs}
    assert "production_database_selection" in subjects
    assert "database_service_endpoint" in subjects


def test_application_big_picture_from_repository_facts(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    summary = _config(result, "application.summary")
    assert summary is not None
    assert "Spring Boot web application" in summary.value
    assert "owners" in summary.value and "pets" in summary.value and "visits" in summary.value

    model = _config(result, "application.data_model")
    assert model is not None
    assert model.value == [
        "owners",
        "pets",
        "specialties",
        "types",
        "vet_specialties",
        "vets",
        "visits",
    ]
    assert {ev.path for ev in model.evidence} >= {
        "src/main/resources/db/mysql/schema.sql",
        "src/main/resources/db/postgres/schema.sql",
    }


def test_readme_application_description_is_surfaced(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    summary = _config(result, "application.summary")
    assert summary is not None
    assert "Spring PetClinic Sample Application" in summary.value
    assert "Spring Boot" in summary.value
    assert "Maven" in summary.value and "Gradle" in summary.value


# --------------------------------------------------------------------------- #
# SQL init
# --------------------------------------------------------------------------- #
def test_sql_init_analyzed(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "startup_order", "startup.sql_init") is not None
    assert "no Flyway/Liquibase" in _in_section(result, "startup_order", "startup.migration_tool").value
    idem = _in_section(result, "startup_order", "startup.sql_init.idempotent")
    assert idem is not None and idem.confidence == "derived"
    assert _in_section(result, "startup_order", "startup.sql_init.mode.postgres").value == "always"


# --------------------------------------------------------------------------- #
# Actuator probes
# --------------------------------------------------------------------------- #
def test_actuator_probe_candidates_and_conditional_paths(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "health_checks", "health.liveness_probe").value == "/actuator/health/liveness"
    assert _in_section(result, "health_checks", "health.readiness_probe").value == "/actuator/health/readiness"
    additional = _in_section(result, "health_checks", "health.additional_paths")
    assert additional.confidence == "unresolved"
    assert "/livez" in additional.value and "/readyz" in additional.value


# --------------------------------------------------------------------------- #
# Containerisation & storage
# --------------------------------------------------------------------------- #
def test_bootbuildimage_without_dockerfile(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "container_image", "image.buildpack_support").value is True
    assert _in_section(result, "container_image", "image.build_command").value == "./gradlew bootBuildImage"
    assert _in_section(result, "container_image", "image.dockerfile").value.startswith("none")


def test_application_pvc_not_required(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    pvc = _in_section(result, "storage", "storage.application_pvc")
    assert pvc.value == "not required"
    assert pvc.confidence == "derived"


def test_database_data_must_persist(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    persistence = _in_section(result, "storage", "storage.database_persistence")
    assert persistence is not None
    assert persistence.value == {
        "profiles": ["mysql", "postgres"],
        "tables": [
            "owners",
            "pets",
            "specialties",
            "types",
            "vet_specialties",
            "vets",
            "visits",
        ],
    }
    assert "database" in persistence.kubernetes_effect.lower()


def test_workload_is_deployment_plus_service(spring_petclinic_repo):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    mapping = next(w for w in result.workload_mappings if w.component == "spring-petclinic")
    assert mapping.kubernetes_kind == "Deployment + ClusterIP Service"


def test_application_profile_keeps_service_and_actuator_candidates_with_database_components(
    spring_petclinic_repo,
):
    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    profile = next(
        profile for profile in result.workload_profiles if profile.name == "spring-petclinic"
    )
    runtime = profile.runtime_deployment_profile

    service = next(
        candidate for candidate in runtime.kubernetes_candidates if candidate.kind == "Service"
    )
    service_fact = next(
        finding
        for finding in result.networking
        if finding.subject == "service.target_port" and finding.value == 8080
    )
    assert service.candidate_role == "companion_object"
    assert all(evidence in service.evidence for evidence in service_fact.evidence)
    assert {
        (candidate.probe_type, candidate.value)
        for candidate in runtime.probe_candidates
    } == {
        ("liveness", "/actuator/health/liveness"),
        ("readiness", "/actuator/health/readiness"),
    }
    assert all(candidate.evidence for candidate in runtime.probe_candidates)
    database_profiles = [
        profile for profile in result.workload_profiles if profile.name in {"mysql", "postgres"}
    ]
    assert all(
        not profile.runtime_deployment_profile.probe_candidates
        for profile in database_profiles
    )


# --------------------------------------------------------------------------- #
# Determinism & read-only guarantees
# --------------------------------------------------------------------------- #
def test_byte_identical_on_repeat(spring_petclinic_repo):
    from repo_analyzer.reporters.json_reporter import to_json

    a = to_json(analyze_repository(str(spring_petclinic_repo), build_system="gradle"))
    b = to_json(analyze_repository(str(spring_petclinic_repo), build_system="gradle"))
    assert a == b


def test_fixture_not_modified(spring_petclinic_repo, tmp_path):
    def digest(root):
        sha = hashlib.sha256()
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            sha.update(path.relative_to(root).as_posix().encode())
            sha.update(path.read_bytes())
        return sha.hexdigest()

    copy = tmp_path / "repo"
    shutil.copytree(spring_petclinic_repo, copy)
    before = digest(copy)
    analyze_repository(str(copy), build_system="gradle")
    assert digest(copy) == before
