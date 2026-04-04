from __future__ import annotations

from streamonitor.enums import Status


def streamer_status_changed(previous_raw: object, current: Status) -> bool:
    if previous_raw is None or previous_raw is False:
        return True
    s = str(previous_raw).strip()
    if not s:
        return True
    try:
        prev_val = int(s)
    except ValueError:
        return True
    return prev_val != current.value
