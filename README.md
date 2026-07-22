# repository-assessment — LLM 주도 Kubernetes 저장소 평가

이 프로젝트의 주 제품 경로는 LLM이 분석 계획과 주제별 해석을 맡고, 제한된 읽기 전용
도구가 선택된 파일에서 근거를 수집하며, 최종 주장을 파일·줄과 대조하는 Kubernetes 이관
평가입니다. 언어나 프레임워크를 미리 가정하지 않고, Dockerfile이나 Compose가 없는
레거시 저장소의 부족한 정보도 명시적인 required input으로 남깁니다.

```bash
uv run repository-assessment assess \
  --repo ./target-repository \
  --output-dir ./output/assessment \
  --base-url http://127.0.0.1:30000/v1 \
  --model Qwen/Qwen3-Coder-30B-A3B-Instruct
```

사용법, 네 가지 산출물, 상태와 제한, OpenShell 실행 방법은
[`docs/ASSESSMENT.md`](./docs/ASSESSMENT.md)를 참고하세요.

## Deterministic analyzer compatibility 경로

`repo-analyzer analyze`는 기존 자동화와 golden fixture를 위한 compatibility 경로로 계속
지원됩니다. 아래 설명과 명령은 이 레거시 분석기에만 적용됩니다.

애플리케이션 소스 레포지토리를 읽어, 엔지니어가 Kubernetes 이관을 시작하는 데 필요한
**P0 수준의 구조적 맥락**을 산출하는 **결정적(deterministic)** 도구입니다.

동일한 레포지토리 내용은 항상 **byte 단위로 동일한 JSON**을 만듭니다. 사실은 source line
근거를 함께 기록하는 Python parser가 추출하며, **LLM이 레포지토리를 직접 들여다보지
않습니다.** 선택적으로 제공되는 Agent Skill은 요청 의도를 감지하고, 이 도구를 호출하고,
결과를 설명하는 얇은 계층일 뿐입니다. 설계 배경은 [`DESIGN.md`](./DESIGN.md)를 참고하세요.

> 범위: `kubernetes-p0` 프로파일만 지원합니다. 이 도구는 Kubernetes/Helm manifest를
> 생성하지 않고, 리소스 사용량을 추측하지 않으며, P1/P2 분석도 하지 않습니다.

## 무엇을 분석하는가

애플리케이션 구성요소와 서비스 토폴로지, image와 Dockerfile, build context/args,
실행 command/entrypoint/worker 수, container port와 공개 host, 환경 변수, Secret 후보,
volume과 영속 데이터, healthcheck, 서비스 의존 관계와 시작 순서, DB migration/초기화
작업, frontend API URL이 build-time인지 runtime인지, Kubernetes workload 초안, 그리고
무엇보다도 **레포지토리만으로는 결정할 수 없는** 운영 입력값을 분석합니다.

현재 세 가지 스택 계열을 지원합니다.

- **Container/compose 스택** (예: FastAPI + Postgres + Nginx): compose 서비스,
  Dockerfile, dotenv, Nginx, Python settings를 분석합니다. **배포용 compose가 없는**
  경우에도 primary Dockerfile(runtime, `EXPOSE`/`--port`, 비-root `USER`, multi-stage
  target, migration stage)과 dotenv config/Secret 후보로부터 구성요소를 합성합니다.
  `documentation/`, `examples/`, `demo/`, `test/` 경로 아래의 compose 파일은 배포
  토폴로지가 **아닌** demo/sample로 취급되어, 그 서비스는 workload가 되지 않습니다.
  각 서비스는 적합한 workload로 매핑됩니다: StatefulSet(database/영속), Job(prestart/init),
  **background queue worker**(inbound port 없는 Celery/taskiq/arq 계열 command → Service
  없는 Deployment), Nginx 정적 자산, 또는 기본 stateless Deployment + ClusterIP Service.
- **Maven / Java 웹 애플리케이션** (예: 외부 servlet container 위의 WAR): `pom.xml`
  (packaging, finalName, Java version, scope별 dependency, profile별 application server),
  `web.xml`(servlet, listener, mapping), Spring application-context datasource(embedded vs
  external)를 분석합니다. WAR packaging, 외부 servlet container 의존성과 그 Maven profile
  대안, 비-root HTTP **context path**, embedded(휘발성) datastore, image build 위험
  (runtime server 다운로드, PID-1 신호 처리, root user), Dockerfile↔README↔POM 교차 검증
  (미정의 실행 profile, JDK version 불일치)을 드러냅니다. Spring `application*.yml`/
  `.properties`(test scope 제외)는 기본 **8080** port, profile별 datasource(external DB
  vs embedded), datasource/JWT/keystore 환경 변수를 **ConfigMap(URL) vs Secret(자격증명)**
  후보로 분류하는 데도 기여합니다. POM이 **`spring-boot-starter-actuator`**를 포함하면
  liveness/readiness probe 경로가 `management` base path(기본 `/actuator`, 예: jhipster의
  `/management/health/{liveness,readiness}`)로 산출되고, **`jib-maven-plugin`**은
  Dockerfile 없는 image recipe로 드러납니다.
- **Spring Boot / Gradle 애플리케이션** (예: spring-petclinic): `build.gradle`(적용된
  plugin과 version, Java toolchain, configuration별 dependency), `settings.gradle`
  (project 이름 → artifact 이름), `gradle-wrapper.properties`(고정된 Gradle version),
  `application*.properties`/`application*.yml`(기본 vs profile별 datasource, SQL init,
  Actuator), 그리고 **version catalog**(`gradle/libs.versions.toml`)를 분석합니다 —
  `alias(libs.…)` plugin과 `libs.…` dependency는 실제 coordinate로 해석되어
  WebFlux/Actuator/DB driver를 인식합니다. multi-module 레포에서는 root가 아니라
  **배포 가능한 module**(Spring Boot plugin을 적용한 module, 예: `api/`)을 분석하며,
  DB 관련 사실(H2 default, `SPRING_PROFILES_ACTIVE`, `spring.sql.init`,
  `production_database_selection`)은 **레포에 실제로 database가 있을 때만** 산출합니다 —
  DB 없는 앱에 대해 지어내지 않습니다. **선택된 build system**(Maven과 Gradle이 둘 다
  있으면 둘 다 나열하고, 선택 결과와 전환 방법을 기록 — 결코 "첫 번째 `pom.xml`"이 아님),
  **실행 가능한 Spring Boot JAR**(`bootJar` vs 일반 `jar`, `java -jar`)을 **배포 가능한
  module**의 archive 위치로 해석한 결과(예: submodule의 `api/build/libs/api-*.jar`와
  `./gradlew :api:bootJar` — root `build/libs`가 아님), script가 의존하는 **`-P` build
  property**(예: `-Pinclude-frontend`)를 build-time 제약으로 드러냄, 기본 **8080** port,
  **H2(기본) vs 외부 PostgreSQL/MySQL** profile과 그 환경 변수를 **ConfigMap(URL) vs
  Secret(user/password)** 후보로 분류, **`spring.sql.init`** 시작 초기화(멱등적,
  Flyway/Liquibase 아님), **Actuator** liveness/readiness probe 후보(`add-additional-paths`
  활성화 시에만 `/livez`,`/readyz`), Dockerfile 없는 **`bootBuildImage`** OCI-image build,
  그리고 이 **애플리케이션은 PVC가 필요 없다는 사실**(상태는 database에 저장됨)을 드러냅니다.

모든 finding에는 다음 라벨이 붙습니다.

- `explicit` — 파일에 직접 명시된 사실.
- `derived` — 2개 이상의 explicit 사실을 결합한 결론(모든 근거를 연결함).
- `unresolved` — 레포지토리만으로 결정할 수 없음. 이유, 필요한 입력, 그리고 임의
  기본값을 만들지 않았다는 사실을 기록함.

이 도구가 추측을 거부하는 값: replica 수, CPU/memory, PVC 크기, StorageClass,
IngressClass, HPA, PodDisruptionBudget, DB HA/backup.

## 요구사항

- Python ≥ 3.12
- [`uv`](https://docs.astral.sh/uv/)

## 설치

```bash
uv sync
```

`.venv`를 생성하고 패키지(editable)와 dev dependency를 설치합니다.

## 사용법 (CLI)

```bash
uv run repo-analyzer analyze \
  --repo ./target-repository \
  --profile kubernetes-p0 \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md \
  --brief-output ./output/brief.md
```

- `--repo` (필수): 레포지토리 경로 (읽기 전용, 절대 수정하지 않음).
- `--profile`: 기본값 `kubernetes-p0` (지원되는 유일한 profile).
- `--build-system`: `auto`(기본) | `gradle` | `maven`. 레포에 build system이 둘 이상
  있을 때 어느 것을 분석할지 강제합니다. `auto`는 결정적으로 선택하고, 그 선택(및 전환
  방법)을 결과에 기록합니다.
- `--git-ref`: 추적성을 위해 metadata에 기록할 commit/ref (선택).
- `--json-output`/`--markdown-output`/`--brief-output`가 모두 없으면 JSON을 stdout으로
  출력합니다.
- `--brief-output`: 7문항 migration JSON만 사람이 읽기 좋은 Markdown brief로 씁니다.

커밋된 golden fixture로 시험해 볼 수 있습니다.

```bash
# compose 스택 (FastAPI + Postgres + Nginx)
uv run repo-analyzer analyze \
  --repo tests/fixtures/full-stack-fastapi \
  --json-output ./output/analysis.json \
  --markdown-output ./output/report.md

# 외부 servlet container 위의 Maven WAR (jpetstore-6)
uv run repo-analyzer analyze \
  --repo tests/fixtures/jpetstore-6 \
  --json-output ./output/jpetstore.json \
  --markdown-output ./output/jpetstore.md

# Spring Boot + Gradle (spring-petclinic; build system이 둘 다 있어 Gradle을 분석)
uv run repo-analyzer analyze \
  --repo tests/fixtures/spring-petclinic \
  --build-system gradle \
  --json-output ./output/spring-petclinic.json \
  --markdown-output ./output/spring-petclinic.md
```

커밋된 예시 출력은 [`examples/`](./examples/)에 있습니다.

## 사용법 (Python / 임의의 agent runtime)

```python
from integrations.tool import analyze_repository

result = analyze_repository("./target-repository", profile="kubernetes-p0")
if result["ok"]:
    analysis = result["analysis"]        # JSON-safe dict, 전체 schema
else:
    print(result["error"])               # 구조화된 error, 절대 raise하지 않음
```

OpenAI 호환 function schema는 [`integrations/tool-schema.json`](./integrations/tool-schema.json)에
있습니다. runtime에 독립적이라 OpenShell/Ollama loop나 임의의 function-calling agent에서
사용할 수 있습니다.

## 출력 schema

JSON 결과는 다음 최상위 section을 포함합니다(안정적인 key 순서).

`schema_version`, `repository`, `detected_files`, `components`,
`workload_mappings`, `networking`, `configuration`, `secrets`, `storage`,
`runtime_dependencies`, `startup_order`, `health_checks`,
`build_time_constraints`, `container_image`, `unresolved_operational_inputs`,
`warnings`, `unsupported_constructs`.

`runtime_dependencies`는 외부 서비스/datastore(또는 embedded된 휘발성 datastore)를
나열합니다. `container_image`는 image build/run 사실과 위험(base image, build/start
command, runtime server 다운로드, 신호 처리, root user)을 보고합니다.

각 주요 finding은 다음과 같은 형태입니다.

```json
{
  "subject": "backend.container_port",
  "value": 8000,
  "confidence": "derived",
  "kubernetes_effect": "backend Service targetPort candidate",
  "evidence": [
    { "path": "compose.yml", "selector": "$.services.backend.healthcheck.test",
      "symbol": "healthcheck.url", "start_line": 113, "end_line": 113 }
  ]
}
```

Markdown 보고서는 workload 중심으로 작성되며 7가지 P0 질문에 답합니다: 어떤 구성요소가
있는가, 그것들이 어떤 Kubernetes workload로 매핑되는가, 어떤 port/Service가 필요한가,
무엇이 영속되어야 하는가, 어떤 ConfigMap/Secret이 필요한가, 무엇이 먼저 실행되어야
하는가, 그리고 레포지토리만으로는 무엇을 결정할 수 없는가.

## Agent Skill 통합

[`skills/kubernetes-repository-analyzer/SKILL.md`](./skills/kubernetes-repository-analyzer/SKILL.md)는
얇은 wrapper입니다. 이관 분석 의도(예: "이 레포를 Kubernetes로 이관하기 위해
분석해줘", "analyze this repo for Kubernetes migration", 또는
`/analyze-k8s-repo <repository-path>`)에 반응하며, Dockerfile 구문 질문, 일반적인
Kubernetes 질문, 코드 리팩터링, 기존 manifest 리뷰에는 명시적으로 반응하지 **않습니다.**

Skill 규칙: 먼저 Python 도구를 호출하고, 도구가 반환한 것만 보고하며,
`explicit`/`derived`/`unresolved` 라벨을 보존하고, 운영 값을 추측하지 않으며, 실패
시에는 일반적인 Kubernetes 지식으로 대체하지 않고 실패한 단계·원인·확인할 파일을
보고합니다.

## 결정성

timestamp, 소요 시간, 임시 경로, 절대 경로, 무작위 ID, 순서가 없는 set은 출력에 도달하지
않습니다. 경로는 repo-relative POSIX입니다. list는 정렬되어 있습니다. JSON은 UTF-8,
2-space indent, 고유한 key 순서를 가집니다. 동일 입력 → 동일 byte(테스트로 강제됨).

## 테스트

```bash
uv run pytest
```

커버리지: parser별 단위 테스트(compose, dockerfile, dotenv, nginx, python-settings,
maven, webxml, spring-xml, **gradle, spring-properties, sql-init**), 세 개의 rule/golden
fixture 통합 suite(compose 스택, Maven WAR, **Spring Boot + Gradle**), category 수준의
일반화 테스트(implicit Dockerfile 해석, published-port fallback, Maven-without-compose,
**build-system 선택, 합성 non-fixture 레포에서의 Spring Boot 사실**), **k8s-manifest
ground-truth 비교**(분석기의 source-only 출력 vs spring-petclinic 자체 `k8s/` manifest),
byte 단위 결정성 테스트, "target repo는 절대 수정되지 않음" 테스트, 그리고 missing-file /
bad-profile / malformed-input / unsupported-construct 테스트가 포함됩니다. 모든 fixture는
로컬이며, **어떤 테스트도 네트워크에 접근하지 않습니다.**

Golden fixture는 P0 관련 파일을 고정 커밋으로 로컬 복제한 것입니다.

- `tests/fixtures/full-stack-fastapi/` — [`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template)
  @ `4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`.
- `tests/fixtures/jpetstore-6/` — [`mybatis/jpetstore-6`](https://github.com/mybatis/jpetstore-6)
  @ `5a7cc780505b88a60779b3e3c0a50b0e404cfb2d` (`mvnw`/`mvnw.cmd`는 최소 placeholder로,
  build-tool 감지를 위한 존재 여부만 사용됨).
- `tests/fixtures/spring-petclinic/` — [`spring-projects/spring-petclinic`](https://github.com/spring-projects/spring-petclinic)
  @ `f182358d02e4a68e52bdbabf55ca7800288511e7` (Spring Boot 4.x; `build.gradle`과
  `pom.xml`을 **둘 다** 포함; `gradlew`/`mvnw`는 존재 여부만 사용하는 placeholder;
  upstream `k8s/` manifest를 ground-truth 참조용으로만 포함 — 분석기는 그것을 읽지 않음).

## 프로젝트 구조

```text
.
├── pyproject.toml
├── README.md
├── DESIGN.md
├── src/repo_analyzer/
│   ├── cli.py                 # argparse entry point
│   ├── models.py              # Pydantic 결과 schema (고정된 key 순서)
│   ├── inventory.py           # 이름/패턴 기반 파일 탐색
│   ├── analyzer.py            # orchestration (모든 filesystem 읽기)
│   ├── parsers/               # compose, dockerfile, dotenv, nginx, python_settings,
│   │                          #   maven, webxml, spring_xml, xml_source
│   ├── rules/                 # kubernetes_p0 (engine) + java_webapp (Maven/WAR rules)
│   └── reporters/             # json_reporter, markdown_reporter
├── skills/kubernetes-repository-analyzer/SKILL.md
├── integrations/
│   ├── tool.py                # analyze_repository(...) wrapper
│   └── tool-schema.json       # OpenAI 호환 function schema
├── examples/                  # 커밋된 golden-fixture 출력
└── tests/
    ├── fixtures/full-stack-fastapi/
    └── test_*.py
```

## 제한사항 및 비-목표

- Compose override 파일은 감지되지만 **병합되지 않습니다**(warning 발생). 분석은 primary
  compose 파일을 기준으로 합니다.
- manifest/Helm 생성, 리소스 사용량 추측, P1/P2 분석은 하지 않습니다.
- 지원하지 않는 구문은 조용히 무시하지 않고 보고합니다(`warnings` /
  `unsupported_constructs`).
