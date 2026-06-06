from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Callable

import bpy


_IDLE_TIMER_INTERVAL_SECONDS = 0.05
_ACTIVE_TIMER_MIN_SECONDS = 0.001
_ACTIVE_TIMER_MAX_SECONDS = 0.005
_CALLBACK_BUDGET_SECONDS = 0.004
_CALLBACK_MAX_EXECUTIONS = 8
_MAX_STORED_ERRORS = 32
_MAX_STORED_CALLBACK_SAMPLES = 4096


@dataclass(slots=True)
class _ScheduledJob:
    job_id: int
    label: str
    execute: Callable[[], object]
    run_after: float
    dedupe_key: str = ""
    created_at: float = field(default_factory=time.monotonic)
    status: str = "queued"
    cancel_requested: bool = False
    message: str = ""


@dataclass(frozen=True, slots=True)
class JobContinuation:
    execute: Callable[[], object]
    label: str = ""
    delay_seconds: float = 0.0
    dedupe_key: str = ""
    replace_dedupe: bool = False
    message: str = ""


_QUEUE: deque[_ScheduledJob] = deque()
_MAINTENANCE_CALLBACKS: dict[str, Callable[[], None]] = {}
_JOB_HISTORY: dict[int, _ScheduledJob] = {}
_LAST_ERRORS: list[str] = []
_CALLBACK_SAMPLES_MS: list[float] = []
_CALLBACK_OP_SAMPLES: list[int] = []
_CALLBACK_MS_MAX = 0.0
_CALLBACK_OPS_MAX = 0
_QUEUE_DEPTH_MAX = 0
_NEXT_JOB_ID = 1


def _append_error(message: str) -> None:
    _LAST_ERRORS.append(str(message))
    if len(_LAST_ERRORS) > _MAX_STORED_ERRORS:
        del _LAST_ERRORS[:-_MAX_STORED_ERRORS]


def _queued_job_count() -> int:
    return sum(1 for job in _QUEUE if job.status == "queued" and not job.cancel_requested)


def _record_queue_depth() -> int:
    global _QUEUE_DEPTH_MAX
    depth = _queued_job_count()
    if depth > _QUEUE_DEPTH_MAX:
        _QUEUE_DEPTH_MAX = depth
    return depth


def _record_callback_sample(duration_ms: float, executed_ops: int) -> None:
    global _CALLBACK_MS_MAX
    global _CALLBACK_OPS_MAX
    duration_ms = float(duration_ms)
    executed_ops = int(executed_ops)
    _CALLBACK_SAMPLES_MS.append(duration_ms)
    _CALLBACK_OP_SAMPLES.append(executed_ops)
    if len(_CALLBACK_SAMPLES_MS) > _MAX_STORED_CALLBACK_SAMPLES:
        del _CALLBACK_SAMPLES_MS[:-_MAX_STORED_CALLBACK_SAMPLES]
        del _CALLBACK_OP_SAMPLES[:-_MAX_STORED_CALLBACK_SAMPLES]
    if duration_ms > _CALLBACK_MS_MAX:
        _CALLBACK_MS_MAX = duration_ms
    if executed_ops > _CALLBACK_OPS_MAX:
        _CALLBACK_OPS_MAX = executed_ops


def _is_interface_locked() -> bool:
    wm = getattr(bpy.context, "window_manager", None)
    return bool(wm is not None and getattr(wm, "is_interface_locked", False))


def _run_maintenance_callbacks() -> None:
    for callback_name, callback in tuple(_MAINTENANCE_CALLBACKS.items()):
        try:
            callback()
        except Exception as exc:
            _append_error(f"Scheduler maintenance callback '{callback_name}' failed: {exc}")


def _pop_next_ready_job(*, force_ready: bool) -> _ScheduledJob | None:
    now = time.monotonic()
    while _QUEUE:
        job = _QUEUE[0]
        if job.cancel_requested or job.status != "queued":
            _QUEUE.popleft()
            if not job.message:
                job.message = "Cancelled before execution."
            if job.status == "queued":
                job.status = "cancelled"
            _JOB_HISTORY[job.job_id] = job
            continue
        if not force_ready and job.run_after > now:
            return None
        _QUEUE.popleft()
        return job
    return None


def _run_job(job: _ScheduledJob) -> bool:
    if job.cancel_requested:
        job.status = "cancelled"
        job.message = job.message or "Cancelled before execution."
        _JOB_HISTORY[job.job_id] = job
        return True

    job.status = "running"
    _JOB_HISTORY[job.job_id] = job
    try:
        result = job.execute()
    except Exception as exc:
        job.status = "failed"
        job.message = str(exc)
        _JOB_HISTORY[job.job_id] = job
        _append_error(f"Scheduler job '{job.label}' failed: {exc}")
        return False

    if isinstance(result, JobContinuation):
        enqueue_job(
            label=result.label or job.label,
            execute=result.execute,
            delay_seconds=result.delay_seconds,
            dedupe_key=result.dedupe_key or job.dedupe_key,
            replace_dedupe=result.replace_dedupe,
        )
        job.status = "completed"
        job.message = str(result.message or "Continued.")
        _JOB_HISTORY[job.job_id] = job
        return True

    if isinstance(result, tuple) and len(result) >= 1:
        success = bool(result[0])
        job.message = str(result[1]) if len(result) > 1 else ""
    else:
        success = True
        job.message = str(result) if result else ""

    job.status = "completed" if success else "failed"
    _JOB_HISTORY[job.job_id] = job
    if not success:
        _append_error(f"Scheduler job '{job.label}' failed: {job.message or 'Unknown failure.'}")
    return success


def _run_scheduler_slice(*, force_ready: bool) -> int:
    if _is_interface_locked():
        return 0
    started_at = time.monotonic()
    executed_ops = 0
    while executed_ops < _CALLBACK_MAX_EXECUTIONS:
        if executed_ops > 0 and (time.monotonic() - started_at) >= _CALLBACK_BUDGET_SECONDS:
            break
        job = _pop_next_ready_job(force_ready=force_ready)
        if job is None:
            break
        _run_job(job)
        executed_ops += 1
        if (time.monotonic() - started_at) >= _CALLBACK_BUDGET_SECONDS:
            break
    return executed_ops


def _adaptive_non_empty_delay(now: float) -> float:
    pending_times = [
        job.run_after
        for job in _QUEUE
        if job.status == "queued" and not job.cancel_requested
    ]
    if not pending_times:
        return _IDLE_TIMER_INTERVAL_SECONDS

    depth = len(pending_times)
    depth_factor = min(float(depth), float(_CALLBACK_MAX_EXECUTIONS)) / float(_CALLBACK_MAX_EXECUTIONS)
    depth_delay = _ACTIVE_TIMER_MAX_SECONDS - depth_factor * (_ACTIVE_TIMER_MAX_SECONDS - _ACTIVE_TIMER_MIN_SECONDS)
    next_ready_in = max(0.0, min(pending_times) - now)
    readiness_delay = max(_ACTIVE_TIMER_MIN_SECONDS, min(_ACTIVE_TIMER_MAX_SECONDS, next_ready_in))
    return max(_ACTIVE_TIMER_MIN_SECONDS, min(_ACTIVE_TIMER_MAX_SECONDS, min(depth_delay, readiness_delay)))


def _timer_callback():
    started = time.perf_counter()
    _run_maintenance_callbacks()
    _record_queue_depth()
    executed_ops = _run_scheduler_slice(force_ready=False)
    _record_queue_depth()
    callback_ms = (time.perf_counter() - started) * 1000.0
    _record_callback_sample(callback_ms, executed_ops)
    if _queued_job_count() > 0:
        return _adaptive_non_empty_delay(time.monotonic())
    return _IDLE_TIMER_INTERVAL_SECONDS


def register() -> None:
    if bpy.app.timers.is_registered(_timer_callback):
        return
    bpy.app.timers.register(
        _timer_callback,
        first_interval=_IDLE_TIMER_INTERVAL_SECONDS,
        persistent=True,
    )


def unregister() -> None:
    global _NEXT_JOB_ID
    if bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.unregister(_timer_callback)
    _QUEUE.clear()
    _MAINTENANCE_CALLBACKS.clear()
    _JOB_HISTORY.clear()
    _LAST_ERRORS.clear()
    reset_runtime_metrics()
    _NEXT_JOB_ID = 1


def register_maintenance_callback(callback_id: str, callback: Callable[[], None]) -> None:
    _MAINTENANCE_CALLBACKS[str(callback_id)] = callback


def unregister_maintenance_callback(callback_id: str) -> None:
    _MAINTENANCE_CALLBACKS.pop(str(callback_id), None)


def enqueue_job(
    *,
    label: str,
    execute: Callable[[], object],
    delay_seconds: float = 0.0,
    dedupe_key: str = "",
    replace_dedupe: bool = False,
) -> int:
    global _NEXT_JOB_ID
    run_after = time.monotonic() + max(0.0, float(delay_seconds))
    dedupe_key = str(dedupe_key or "")
    if dedupe_key and replace_dedupe:
        for pending in _QUEUE:
            if pending.dedupe_key == dedupe_key and pending.status == "queued":
                pending.cancel_requested = True
                pending.status = "cancelled"
                pending.message = "Replaced by newer queued request."
                _JOB_HISTORY[pending.job_id] = pending
    job = _ScheduledJob(
        job_id=_NEXT_JOB_ID,
        label=str(label or f"job-{_NEXT_JOB_ID}"),
        execute=execute,
        run_after=run_after,
        dedupe_key=dedupe_key,
    )
    _NEXT_JOB_ID += 1
    _QUEUE.append(job)
    _record_queue_depth()
    return job.job_id


def has_pending_jobs(*, dedupe_key: str = "") -> bool:
    dedupe_key = str(dedupe_key or "")
    for pending in _QUEUE:
        if pending.status != "queued" or pending.cancel_requested:
            continue
        if dedupe_key and pending.dedupe_key != dedupe_key:
            continue
        return True
    return False


def flush(*, force_ready: bool = False) -> tuple[bool, str]:
    if force_ready:
        now = time.monotonic()
        for pending in _QUEUE:
            if pending.status == "queued" and not pending.cancel_requested:
                pending.run_after = now

    while _QUEUE:
        _run_maintenance_callbacks()
        if _is_interface_locked():
            message = "Scheduler flush blocked while Blender interface is locked."
            _append_error(message)
            return False, message
        job = _pop_next_ready_job(force_ready=force_ready)
        if job is None:
            break
        if not _run_job(job):
            return False, job.message or "Scheduled job failed."

    return True, ""


def job_status(job_id: int) -> tuple[str, str]:
    job = _JOB_HISTORY.get(int(job_id))
    if job is None:
        return "unknown", ""
    return job.status, job.message


def recent_errors() -> tuple[str, ...]:
    return tuple(_LAST_ERRORS)


def reset_runtime_metrics() -> None:
    global _CALLBACK_MS_MAX
    global _CALLBACK_OPS_MAX
    global _QUEUE_DEPTH_MAX
    _CALLBACK_SAMPLES_MS.clear()
    _CALLBACK_OP_SAMPLES.clear()
    _CALLBACK_MS_MAX = 0.0
    _CALLBACK_OPS_MAX = 0
    _QUEUE_DEPTH_MAX = 0


def runtime_metrics_snapshot() -> dict[str, object]:
    return {
        "scheduler_callback_ms_max": float(_CALLBACK_MS_MAX),
        "scheduler_callback_ops_max": int(_CALLBACK_OPS_MAX),
        "scheduler_queue_depth_max": int(_QUEUE_DEPTH_MAX),
        "scheduler_callback_samples_ms": tuple(float(value) for value in _CALLBACK_SAMPLES_MS),
        "scheduler_callback_op_samples": tuple(int(value) for value in _CALLBACK_OP_SAMPLES),
    }
