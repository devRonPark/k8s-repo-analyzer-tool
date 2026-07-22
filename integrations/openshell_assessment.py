"""Thin process adapter for running an assessment inside NVIDIA OpenShell."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from pydantic import BaseModel, ConfigDict

from repository_assessment.cli import (
    JsonLineEventSink,
    RuntimeConfig,
    execute_assessment,
)
from repository_assessment.contracts import RunLimits


class OpenShellAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    repository_path: str
    output_directory: str
    revision: str | None = None
    base_url: str = "https://inference.local/v1"
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 60
    limits: RunLimits = RunLimits()
    recorded_responses: str | None = None


def run_openshell_assessment(
    request: OpenShellAssessmentRequest,
    *,
    output: TextIO = sys.stderr,
    cancelled=None,
) -> dict:
    """Map one OpenShell runtime request to the provider-neutral composition root."""

    result = execute_assessment(
        RuntimeConfig(
            repository=request.repository_path,
            output_directory=request.output_directory,
            run_id=request.run_id,
            revision=request.revision,
            base_url=request.base_url,
            model=request.model,
            api_key=os.environ.get(request.api_key_env),
            recorded_responses=request.recorded_responses,
            timeout_seconds=request.timeout_seconds,
            limits=request.limits,
        ),
        JsonLineEventSink(output, cancelled=cancelled),
    )
    return {"schema_version": "openshell-assessment-result/v1", **result}
