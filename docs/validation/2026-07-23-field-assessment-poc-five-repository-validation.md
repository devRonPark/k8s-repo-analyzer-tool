# Field Assessment POC 5개 저장소 검증

- 검증일: 2026-07-23
- 대상: `skills/kubernetes-field-assessment`
- 입력: `canonical/poc-validation.json`의 canned intake, 고정 SHA, recorded POC 결과
- 판정: 5개 저장소 모두 evidence-backed package 또는 partial result로 분류된다.

## 결과 요약

| 저장소 | 분류 | 요약 |
| --- | --- | --- |
| `jbangdev/jbang` | `partial_result` | CLI 도구로 분류했고 상주 웹 workload를 만들지 않는 partial 결과입니다. |
| `spring-petclinic/spring-petclinic-rest` | `evidence_result_backed_diagnosis_package` | Spring Boot REST API 진단 패키지를 Evidence Result 근거로 만들 수 있습니다. |
| `ether/etherpad` | `evidence_result_backed_diagnosis_package` | Node.js web server 진단 패키지를 만들 수 있고, 볼륨 의미는 후속 확인으로 남습니다. |
| `pypa/pipx` | `partial_result` | Python CLI 도구로 분류했고 상주 workload 없이 partial 결과를 유지합니다. |
| `searxng/searxng` | `partial_result` | Python web 앱 근거는 있으나 이미지 provenance와 네트워크 정책이 남아 partial 결과입니다. |

분류 수:

- `evidence_result_backed_diagnosis_package`: 2
- `partial_result`: 3
- `explicit_failure`: 0
- `invalid_result`: 0

## 확인한 계약

- 다섯 저장소 모두 canned intake가 `application_shape`,
  `current_execution_shape`, `analysis_purpose` 질문을 채운다.
- partial result는 checked Evidence Result와 partial reason을 보존한다.
- 진단 패키지는 Evidence Result appendix를 통해 주요 판단을 추적할 수 있다.
- 실패 결과가 생기면 `failed_stage`와 `reason` 없이는 유효한 결과로 보지 않는다.
- 근거가 부족한 경우 일반 Kubernetes 조언으로 채우지 않고 partial 또는 failure로 남긴다.

## 다음 구현 우선순위

1. CLI와 tooling 저장소를 억지 상주 서비스로 만들지 않고 non-resident 또는 Job-like 이관 후보로 표현한다.
2. 소스 포트, 컨테이너 포트, prebuilt image처럼 source context가 다른 증거를 더 명확히 구분한다.
3. replica, resource request, ingress host, StorageClass, production Secret 값 같은 운영 입력은 기본값으로 채우지 않고 진단 패키지의 확인 필요 항목으로 유지한다.
