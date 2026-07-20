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
