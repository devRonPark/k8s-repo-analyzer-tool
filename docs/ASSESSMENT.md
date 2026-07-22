# LLM 주도 Kubernetes 저장소 평가

`repository-assessment`는 LLM이 분석 계획과 주제별 해석을 맡고, 제한된 읽기 전용
도구가 선택된 저장소 근거를 수집하며, 근거 검사기가 최종 주장을 실제 파일과 줄에
대조하는 평가 CLI입니다. Dockerfile이나 Compose 파일이 없는 레거시 저장소도 평가할
수 있지만, 저장소가 증명하지 못한 값은 추측하지 않고 required input으로 남깁니다.

## 로컬 실행

OpenAI Chat Completions 호환 모델 서버를 사용할 때:

```bash
export OPENAI_API_KEY="..."
uv run repository-assessment assess \
  --repo ./target-repository \
  --output-dir ./output/assessment \
  --base-url http://127.0.0.1:30000/v1 \
  --model Qwen/Qwen3-Coder-30B-A3B-Instruct
```

네트워크나 모델 없이 커밋된 응답을 재생하는 오프라인 검증:

```bash
UV_CACHE_DIR=.uv-cache uv run --offline repository-assessment assess \
  --repo tests/fixtures/assessment/node-basic \
  --output-dir ./output/assessment-node-basic \
  --recorded-responses tests/fixtures/assessment/recorded/node-basic.json
```

진행 이벤트는 stderr에 JSON Lines로, 최종 요약과 산출물 경로는 stdout에 한 줄 JSON으로
출력됩니다.

## OpenShell 실행

OpenShell은 저장소 안에 별도 에이전트 패키지를 정의하는 방식이 아니라, CLI를 격리해
실행하는 샌드박스 런타임입니다. 평가 CLI가 설치되고 `/app`, `/sandbox/repository`,
`/sandbox/output`이 준비된 런타임 이미지를 사용합니다. filesystem과 process 정책은
정적이므로 이 저장소의 schema-v1 정책을 샌드박스 생성 시 적용해야 합니다.

```bash
openshell sandbox create --policy openshell/policy.yaml --name repository-assessment -- repository-assessment --help
```

컴퓨트 드라이버나 런타임 이미지가 평가 대상을 `/sandbox/repository`에 읽기 전용으로,
출력 디렉터리를 `/sandbox/output`에 쓰기 가능으로 제공한 상태에서 one-shot 명령을
실행합니다.

```bash
openshell sandbox exec -n repository-assessment -- \
  repository-assessment assess \
  --repo /sandbox/repository \
  --output-dir /sandbox/output \
  --base-url https://inference.local/v1 \
  --model Qwen/Qwen3-Coder-30B-A3B-Instruct
```

`https://inference.local/v1`은 OpenShell이 구성된 inference provider로 중계하는 기본
주소입니다. 일반 네트워크 egress를 허용하는 주소가 아닙니다.

## 산출물

성공적으로 결과를 만든 실행은 출력 디렉터리에 정확히 네 파일을 원자적으로 씁니다.

- `migration-inputs.yaml`: 개발자가 다음 이관 단계에 사용할 정규화된 입력과 required input
- `migration-report.md`: 워크로드 중심의 한국어 보고서
- `assessment-details.json`: 검사된 주장, 근거, 충돌을 포함한 전체 기계 결과
- `run-log.json`: 계획, 제한 사용량, 모델 메타데이터, 이벤트와 오류를 포함한 감사 기록

기계 계약은 `migration-assessment/v1`, 실행 로그는 `assessment-run-log/v1`, 프롬프트는
`assessment-prompts/v1` 버전을 사용합니다.

## 상태 의미

실행 상태는 다음 세 값만 사용합니다.

- `completed`: 모든 필수 분석 주제가 `answered`이고 오류나 충돌이 없습니다. exit code 0.
- `completed_with_gaps`: 결과는 생성됐지만 일부 주제가 `partial`, `unresolved`,
  `unsupported`, `contradicted`이거나 제한·검사 오류가 남았습니다. exit code 1.
- `failed`: 취소, 전체 시간 초과, 저장소 접근 실패처럼 평가 결과를 만들 수 없는 치명적
  실패입니다. exit code 3.

CLI 설정 오류는 exit code 2입니다. 주제 상태는 `answered`, `partial`, `unresolved`,
`unsupported`, `contradicted` 중 하나이며, 어떤 상태도 배포 준비 완료나 점수의 의미를
갖지 않습니다.

## 13개 기본 분석 주제

1. `application_identity`
2. `build_profile`
3. `artifact_profile`
4. `runtime_profile`
5. `entrypoint`
6. `networking`
7. `dependencies`
8. `config_and_secret`
9. `storage`
10. `observability`
11. `existing_deploy_hints`
12. `migration_risks`
13. `unknowns`

## 기본 실행 제한

| 제한 | 기본값 |
| --- | ---: |
| 파일 트리 항목 | 20,000 |
| 선택 대상 | 40 |
| 단일 파일 크기 | 524,288 bytes |
| 한 번에 읽는 줄 | 200 |
| 검색 호출 | 20 |
| 검색당 일치 | 100 |
| 분석 계획 라운드 | 2 |
| 모델 호출 | 10 |
| 스키마 복구 | 1 |
| 전체 실행 시간 | 300 seconds |

각 제한은 같은 이름의 CLI 옵션으로 낮추거나 조정할 수 있습니다. 제한에 도달해도 검사
가능한 근거가 있으면 결과를 버리지 않고 `completed_with_gaps`로 반환합니다.

## 보안 경계

- 평가 대상 저장소는 읽기 전용이며 생성·수정·삭제하지 않습니다.
- 경로 탈출, 심볼릭 링크 탈출, 스캔되지 않은 파일 읽기와 중복·과도한 읽기를 거부합니다.
- 저장소 텍스트는 신뢰하지 않는 데이터로 취급하며 도구, 제한, 네트워크, 출력 규칙을
  바꿀 수 없습니다.
- Secret처럼 보이는 값은 도구 결과에서 마스킹되며 production Secret 값을 만들지
  않습니다.
- `openshell/policy.yaml`은 `/app`과 `/sandbox/repository`만 읽기 전용으로,
  `/sandbox/output`과 `/tmp`만 쓰기 가능으로 허용하고 일반 네트워크 egress를 허용하지
  않습니다.
- manifest 생성, replica/resource sizing, PVC 크기, StorageClass, IngressClass, HPA,
  PDB와 플랫폼 정책 결정은 이 평가의 범위 밖입니다.
