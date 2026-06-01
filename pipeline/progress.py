"""Progress events for long-running pipeline jobs (UI streaming)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

ProgressCallback = Callable[[Dict[str, Any]], None]


def emit_progress(
    on_progress: Optional[ProgressCallback],
    stage: str,
    message: str,
    *,
    level: str = "info",
    set_stage: bool = True,
    **extra: Any,
) -> None:
    if not on_progress:
        return
    if set_stage:
        on_progress({"type": "stage", "stage": stage})
    on_progress(
        {
            "type": "log",
            "stage": stage,
            "message": message,
            "level": level,
            **extra,
        }
    )
