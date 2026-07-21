# Task 2 Report: Assemble Profiles From Existing Component Facts

## Status

DONE_WITH_CONCERNS

## Changes

- Added `_emit_workload_profiles(result)` and invoke it from `_finalize_result()` before migration-question generation.
- Projects components, mappings, networking, configuration, secrets, storage, health checks, and Dockerfile image findings into deterministic workload profiles in component order.
- Separates image build facts from runtime facts; emits controller and companion Kubernetes object candidates with evidence types.
- Records container and published ports as exposure candidates, health checks as probe candidates, and deliberately leaves relationships empty for Task 3.
- Added the full-stack FastAPI integration coverage with provenance assertions.

## TDD Evidence

- RED: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py::test_full_stack_fastapi_profiles_group_build_and_runtime`
  failed because `result.workload_profiles` was empty.
- GREEN: the same focused command passed after implementation.
- Full suite: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q` passed.

## Concern

The task brief expected the backend build context to be `./backend`, but the checked-in Compose fixture explicitly declares `context: .` and `dockerfile: backend/Dockerfile`. The integration test asserts `.` to preserve the existing repository fact rather than rewrite it.

## Review Fixes

- Scoped networking, storage, and health findings to their service-qualified subject prefix. Shared Compose file paths no longer attach a finding to every service profile.
- Kept configuration and secret matching based on each component's environment and secret fields, because their finding subjects are global config/secret names.
- Added regression assertions that PVC, Ingress, and health/probe candidates do not leak between full-stack services. Relationships remain empty.
- The emitted profiles continue to satisfy provenance validation through the analyzed full-stack fixture and schema test suite.

## Review Fix Test Results

- Focused: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py` passed (2 tests).
- Full suite: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q` passed (247 tests).
