"""Compare the source-derived analysis against spring-petclinic's own ``k8s/``
manifests.

The manifests are *ground truth reference only* — the analyzer never reads them.
Here we parse them in the test, confirm the tool's source-only analysis agrees on
the facts a manifest author must know, and turn the one meaningful *difference*
(the manifest probes ``/livez``/``/readyz``, which need a setting the repo does
not contain) into an explicit regression assertion.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from repo_analyzer.analyzer import analyze_repository


def _load_docs(path: Path) -> list[dict]:
    yaml = YAML(typ="safe")
    return [d for d in yaml.load_all(path.read_text()) if d]


def _find_kind(docs: list[dict], kind: str) -> dict:
    return next(d for d in docs if d.get("kind") == kind)


def _in_section(result, section, subject):
    return next((f for f in getattr(result, section) if f.subject == subject), None)


def _petclinic_manifest(repo: Path) -> list[dict]:
    return _load_docs(repo / "k8s" / "petclinic.yml")


def test_service_target_port_matches_manifest(spring_petclinic_repo):
    docs = _petclinic_manifest(spring_petclinic_repo)
    service = _find_kind(docs, "Service")
    manifest_target_port = service["spec"]["ports"][0]["targetPort"]
    assert manifest_target_port == 8080  # ground truth

    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "networking", "service.target_port").value == manifest_target_port


def test_manifest_active_profile_is_a_supported_profile(spring_petclinic_repo):
    docs = _petclinic_manifest(spring_petclinic_repo)
    deployment = _find_kind(docs, "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e.get("value") for e in container.get("env", [])}
    active_profile = env.get("SPRING_PROFILES_ACTIVE")
    assert active_profile == "postgres"  # ground truth

    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    # The tool must know this profile exists and needs an external DB.
    assert _in_section(result, "runtime_dependencies", f"database.profile.{active_profile}") is not None


def test_manifest_uses_http_probes_tool_provides_candidates(spring_petclinic_repo):
    docs = _petclinic_manifest(spring_petclinic_repo)
    deployment = _find_kind(docs, "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert "livenessProbe" in container and "readinessProbe" in container  # ground truth

    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "health_checks", "health.liveness_probe") is not None
    assert _in_section(result, "health_checks", "health.readiness_probe") is not None


def test_livez_readyz_difference_is_surfaced(spring_petclinic_repo):
    """The manifest probes /livez and /readyz, which only work because it injects
    ``add-additional-paths=true`` via env. The repo source does NOT set that, so
    the tool must default to /actuator/health/* and flag /livez,/readyz as
    conditional rather than blindly emitting them."""

    docs = _petclinic_manifest(spring_petclinic_repo)
    deployment = _find_kind(docs, "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    manifest_liveness_path = container["livenessProbe"]["httpGet"]["path"]
    assert manifest_liveness_path == "/livez"  # ground truth

    raw = (spring_petclinic_repo / "k8s" / "petclinic.yml").read_text()
    assert "add-additional-paths" in raw  # the manifest enables it

    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    # Source does not enable it -> conditional, not confirmed.
    additional = _in_section(result, "health_checks", "health.additional_paths")
    assert additional is not None and additional.confidence == "unresolved"
    assert not any(f.subject == "health.livez" for f in result.health_checks)
    assert any(u.subject == "health_probe_additional_paths" for u in result.unresolved_operational_inputs)


def test_app_deployment_has_no_pvc(spring_petclinic_repo):
    docs = _petclinic_manifest(spring_petclinic_repo)
    deployment = _find_kind(docs, "Deployment")
    spec = deployment["spec"]["template"]["spec"]
    volumes = spec.get("volumes", [])
    # The only app volume is a projected secret (service binding), never a PVC.
    assert not any("persistentVolumeClaim" in v for v in volumes)  # ground truth

    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    assert _in_section(result, "storage", "storage.application_pvc").value == "not required"


def test_manifest_db_credentials_come_from_secret(spring_petclinic_repo):
    db_docs = _load_docs(spring_petclinic_repo / "k8s" / "db.yml")
    secret = _find_kind(db_docs, "Secret")
    assert "password" in secret["stringData"]  # ground truth: creds live in a Secret

    result = analyze_repository(str(spring_petclinic_repo), build_system="gradle")
    secret_subjects = {f.subject for f in result.secrets}
    assert "secret.POSTGRES_PASS" in secret_subjects
