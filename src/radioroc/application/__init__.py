"""Shared synchronous jobs; callers choose their worker/thread adapter."""

from .jobs import CancellationToken, JobCancelled, JobEvent, JobBusyError

__all__ = ["CancellationToken", "JobCancelled", "JobEvent", "JobBusyError"]
