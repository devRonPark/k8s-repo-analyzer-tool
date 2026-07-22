"""Centralized quotas and end-to-end deadline for an assessment run."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .contracts import RunLimits


class RunControlError(RuntimeError):
    pass


class RunDeadlineExceeded(RunControlError):
    pass


class RunCancelled(RunControlError):
    pass


class RunQuotaExceeded(RunControlError):
    pass


@dataclass
class RunControl:
    limits: RunLimits
    clock: Callable[[], float] | None = None
    cancelled: Callable[[], bool] = lambda: False
    started: float = field(init=False)
    model_calls: int = 0
    topic_batches: int = 0
    submission_calls: int = 0

    def __post_init__(self) -> None:
        if self.clock is None:
            self.clock = time.monotonic
        self.started = self.clock()

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.total_seconds - (self.clock() - self.started))

    def guard(self) -> None:
        if self.cancelled():
            raise RunCancelled("assessment was cancelled")
        if self.remaining_seconds() <= 0:
            raise RunDeadlineExceeded("total run time limit was exceeded")

    def reserve_model_call(self) -> None:
        self.guard()
        if self.model_calls >= self.limits.model_calls:
            raise RunQuotaExceeded("model_calls limit exhausted")
        self.model_calls += 1

    def reserve_topic_batch(self) -> None:
        self.guard()
        if self.topic_batches >= self.limits.max_topic_batches:
            raise RunQuotaExceeded("topic_batches limit exhausted")
        self.topic_batches += 1

    def reserve_submission_call(self) -> None:
        self.guard()
        if self.submission_calls >= self.limits.max_submission_tool_calls:
            raise RunQuotaExceeded("submission_calls limit exhausted")
        self.submission_calls += 1

    def can_attempt(self, stage_timeout_seconds: float, delay_seconds: float = 0) -> bool:
        return self.remaining_seconds() >= stage_timeout_seconds + delay_seconds
