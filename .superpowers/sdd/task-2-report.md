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

## Re-review Fixes

- Restored generic `app.*` and `service.*` networking facts only when analysis produces exactly one component; multi-component profiles continue to use component-qualified ownership and never use shared Compose paths.
- Restored generic Spring liveness/readiness findings only for a single component, while limiting health-derived probe candidates to generic liveness/readiness or component-qualified health path/exec findings.
- Matched port exposure provenance to the component-specific or generic application/service port fact, preferring explicit application ports over default and Service target-port facts.
- Added end-to-end Spring Boot workload-profile coverage for a single-component repository, asserting the 8080 exposure evidence and the liveness/readiness candidates.

## Re-review Fix Test Results

- Spring regression: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py::test_single_spring_boot_profile_uses_generic_port_and_probe_facts` passed (1 test).
- Focused: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py` passed (3 tests).
- Full suite: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q` passed (248 tests).

## Remaining Published-Port Fix

- Fixed `_published_port_number()` to report the host-side published port for mapped Compose ports while preserving the container-side port candidate separately.
- Protocol suffixes are stripped before parsing; bare ports continue to resolve to themselves.
- Added regression coverage for `3000:8080`, `127.0.0.1:3000:8080`, `8080`, and `/tcp`, plus an end-to-end profile assertion with unequal host/container ports.

## Fix Test Results

- Focused: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py` passed (5 tests).
- Full suite: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q` passed (248 tests).

## Published-Port Evidence Fix

- Emit a component-scoped `networking` finding for each valid published Compose host port while the original `Located` port entry is available.
- Published-port exposure candidates now use the matching finding evidence, retaining exact Compose selectors such as `$.services.api.ports[0]` instead of broad service mapping evidence.
- Kept published host-port and container-port candidate separation and left relationships unchanged for Task 3.
- Regression coverage verifies evidence exists for every published candidate and points to each specific Compose `ports[...]` entry.

## Published-Port Evidence Test Results

- Focused: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q tests/test_workload_profiles.py` passed (5 tests).
- Full suite: `UV_CACHE_DIR=.uv-cache /home/daolts/.local/bin/uv run pytest -q` passed (250 tests).
