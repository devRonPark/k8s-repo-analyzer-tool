# Task 1 Report: Add Workload Profile Models

## Status

DONE

## Implemented

- Added `RelationshipType` and `KubernetesObjectKind` literal aliases.
- Added `WorkloadRelationship`, `ImageBuildProfile`, `ExposureCandidate`, `ProbeCandidateProfile`, `KubernetesObjectCandidate`, `RuntimeDeploymentProfile`, and `WorkloadProfile` to `src/repo_analyzer/models.py`.
- Added `AnalysisResult.workload_profiles` as an additive field after `components`.
- Added the requested explicit schema serialization test in `tests/test_workload_profiles_schema.py`.

The existing `AnalysisResult` fields remain unchanged. The new schema keeps build facts separate from runtime facts, models Kubernetes entries as candidates with distinct workload-controller and companion-object roles, and supports evidence and unresolved/open-decision fields for derived claims.

## TDD Evidence

1. Added the brief's schema test before production changes.
2. Focused RED run:

   `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles_schema.py`

   Failed during collection with `ImportError: cannot import name 'ImageBuildProfile'`.
3. Added the model definitions and `AnalysisResult.workload_profiles`.
4. Focused GREEN run:

   `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles_schema.py`

   Passed: `1 passed`.

5. Full suite:

   `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`

   Passed: `240 passed`.

6. `git diff --check` passed.

## Commit

Commit created after verification with message:

`feat: add workload profile schema`

## Concerns

None.

## Review Fixes

- Added `ProfileEvidenceType` and required `evidence_type` fields to workload
  relationships, exposure candidates, probe candidates, and Kubernetes object
  candidates.
- Added `RuntimeDeploymentProfile.exposure_candidates` and profile-level
  `evidence`.
- Added validation that rejects non-empty image build or runtime deployment
  profiles without profile evidence or explicit unresolved input.
- Updated schema tests to serialize typed evidence sources and reject
  unsupported non-empty profile claims.

## Fix TDD And Verification

1. Focused RED run failed with the requested typed evidence fields rejected as
   extra inputs and unsupported profiles accepted without provenance.
2. Focused GREEN run:

   `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles_schema.py`

   Passed: `4 passed`.
3. Full suite:

   `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q`

   Passed.
4. `git diff --check` passed.

## Fix Commit

`4e6e7c6 fix: require workload profile provenance`

## Remaining Review Finding Fix

- Added profile-level `open_decisions: list[str]` to `ImageBuildProfile` and
  `RuntimeDeploymentProfile`.
- Updated both provenance validators so profile-level open-decision text is
  accepted alongside line evidence and unresolved text.
- Kept the existing rejection coverage and added positive coverage for both
  profile types backed only by open-decision text.
- Updated the Task 1 plan target schema and provenance rule to document the
  profile-level field consistently.

## Final Verification

- Focused schema suite: `6 passed`.
- Full suite: `245 passed`.
- `git diff --check` passed.
