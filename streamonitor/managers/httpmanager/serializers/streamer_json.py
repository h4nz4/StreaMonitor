from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

if TYPE_CHECKING:
    from streamonitor.bot import Bot


def sanitize_for_json(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def _web_rows_as_dicts(streamer: Bot) -> list[dict[str, str]]:
    rows = []
    for label, value in streamer.web_ui_rows():
        rows.append({"label": str(label), "value": str(value)})
    return rows


def streamer_detail_dict(streamer: Bot, *, refresh_file_list: bool = True) -> dict[str, Any]:
    if refresh_file_list:
        streamer.cache_file_list()
    data = dict(streamer.export())
    data["siteslug"] = streamer.siteslug
    data["url"] = streamer.url
    data["recording"] = streamer.recording
    data["status_code"] = streamer.sc.value
    data["status_message"] = streamer.status()
    data["web_ui_rows"] = _web_rows_as_dicts(streamer)
    last_info = getattr(streamer, "lastInfo", None) or {}
    data["last_info"] = sanitize_for_json(last_info) if last_info else {}
    data["output_folder"] = streamer.outputFolder
    data["total_recordings_bytes"] = streamer.video_files_total_size
    return data


def video_download_query_url(username: str, site: str, filename: str) -> str:
    q = urlencode({"username": str(username), "site": str(site), "filename": str(filename)})
    return f"/video?{q}"


def streamer_recordings_list(streamer: Bot, *, sort_by_size: bool) -> list[dict[str, Any]]:
    streamer.cache_file_list()
    videos = list(streamer.video_files)
    if sort_by_size:
        videos.sort(key=lambda v: v.filesize, reverse=True)
    else:
        videos.sort(key=lambda v: v.filename, reverse=True)
    out: list[dict[str, Any]] = []
    for v in videos:
        out.append(
            {
                "filename": v.filename,
                "shortname": v.shortname,
                "filesize": v.filesize,
                "human_readable_filesize": v.human_readable_filesize,
                "mimetype": v.mimetype,
                "download_url": video_download_query_url(streamer.username, streamer.site, v.filename),
            }
        )
    return out


def streamer_status_dict(streamer: Bot, *, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        try:
            streamer.sc = streamer.getStatus()
        except Exception:
            pass
    return {
        "username": streamer.username,
        "site": streamer.site,
        "siteslug": streamer.siteslug,
        "running": streamer.running,
        "recording": streamer.recording,
        "status_code": streamer.sc.value,
        "status_message": streamer.status(),
        "ok": True,
    }
