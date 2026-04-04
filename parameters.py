import json
import os
import sys
from pathlib import Path
from typing import Any

import environ

env = environ.Env()
if os.path.exists(".env"):
    environ.Env.read_env(".env")

CONFIG_PATH = env.str("STRMNTR_CONFIG", "config.json")
_default_sqlite_path = Path(CONFIG_PATH).expanduser().resolve().parent / "streamonitor.db"

WEB_SETTINGS_PATH = Path(CONFIG_PATH).expanduser().resolve().parent / "web_settings.json"

_file_settings: dict[str, Any] = {}

# Populated by apply_runtime_settings()
DOWNLOADS_DIR: str
DATABASE_URL: str
MIN_FREE_DISK_PERCENT: float
DEBUG: bool
HTTP_USER_AGENT: str
CHB_PROXY_TEST_URL: str
CHB_CF_CLEARANCE: str
CHB_USER_AGENT: str
REQUESTS_HTTP_PROXY: str
REQUESTS_NO_PROXY: str
REQUESTS_PROXIES: dict
FFMPEG_PATH: str
WANTED_RESOLUTION: int
WANTED_RESOLUTION_PREFERENCE: str
CONTAINER: str
VR_FORMAT_SUFFIX: bool
FFMPEG_READRATE: float
SEGMENT_TIME: str | None
WEBSERVER_HOST: str
WEBSERVER_PORT: int
WEBSERVER_SKIN: str
WEB_LIST_FREQUENCY: int
WEB_STATUS_FREQUENCY: int
WEB_THEATER_MODE: bool
WEB_CONFIRM_DELETES: str
WEBSERVER_PASSWORD: str

RESOLUTION_PREF_CHOICES = (
    "exact",
    "exact_or_least_higher",
    "exact_or_highest_lower",
    "closest",
)

SETTINGS_FORM_GROUPS: list[dict[str, Any]] = [
    {
        "title": "Recording",
        "fields": [
            {"key": "WANTED_RESOLUTION", "env": "STRMNTR_RESOLUTION", "type": "int", "label": "Target resolution height (px)"},
            {"key": "WANTED_RESOLUTION_PREFERENCE", "env": "STRMNTR_RESOLUTION_PREF", "type": "choice", "choices": RESOLUTION_PREF_CHOICES, "label": "Resolution match policy"},
            {"key": "CONTAINER", "env": "STRMNTR_CONTAINER", "type": "str", "label": "Output container (mkv, mp4, …)"},
            {"key": "VR_FORMAT_SUFFIX", "env": "STRMNTR_VR_FORMAT_SUFFIX", "type": "bool", "label": "VR filename suffix"},
            {"key": "FFMPEG_PATH", "env": "STRMNTR_FFMPEG_PATH", "type": "str", "label": "ffmpeg binary path"},
            {"key": "FFMPEG_READRATE", "env": "STRMNTR_FFMPEG_READRATE", "type": "float", "label": "ffmpeg -readrate"},
            {"key": "SEGMENT_TIME", "env": "STRMNTR_SEGMENT_TIME", "type": "optional_str", "label": "Segment time (seconds or hh:mm:ss, empty = off)"},
        ],
    },
    {
        "title": "HTTP client",
        "fields": [
            {"key": "HTTP_USER_AGENT", "env": "STRMNTR_USER_AGENT", "type": "str", "label": "Default HTTP User-Agent"},
            {"key": "REQUESTS_HTTP_PROXY", "env": "STRMNTR_HTTP_PROXY", "type": "str", "label": "HTTP(s) proxy URL (empty = none)"},
            {"key": "REQUESTS_NO_PROXY", "env": "STRMNTR_NO_PROXY", "type": "str", "label": "NO_PROXY value"},
            {"key": "CHB_PROXY_TEST_URL", "env": "STRMNTR_CB_PROXY_TEST_URL", "type": "str", "label": "Chaturbate proxy test URL"},
            {"key": "CHB_CF_CLEARANCE", "env": "STRMNTR_CB_CF_CLEARANCE", "type": "str", "label": "Chaturbate cf_clearance cookie"},
            {"key": "CHB_USER_AGENT", "env": "STRMNTR_CB_USER_AGENT", "type": "str", "label": "Chaturbate-specific User-Agent"},
        ],
    },
    {
        "title": "Web UI",
        "fields": [
            {"key": "WEB_LIST_FREQUENCY", "env": "STRMNTR_LIST_FREQ", "type": "int", "label": "Main list refresh (seconds)"},
            {"key": "WEB_STATUS_FREQUENCY", "env": "STRMNTR_STATUS_FREQ", "type": "int", "label": "Recording page status refresh (seconds)"},
            {"key": "WEB_THEATER_MODE", "env": "STRMNTR_THEATER_MODE", "type": "bool", "label": "Theater mode"},
            {"key": "WEB_CONFIRM_DELETES", "env": "STRMNTR_CONFIRM_DEL", "type": "str", "label": 'Confirm deletes (empty / MOBILE / "true")'},
            {"key": "WEBSERVER_PASSWORD", "env": "STRMNTR_PASSWORD", "type": "password", "label": "Web password (empty = no login)"},
        ],
    },
    {
        "title": "Other",
        "fields": [
            {"key": "MIN_FREE_DISK_PERCENT", "env": "STRMNTR_MIN_FREE_SPACE", "type": "float", "label": "Minimum free disk space (%)"},
            {"key": "DEBUG", "env": "STRMNTR_DEBUG", "type": "bool", "label": "Debug logging"},
        ],
    },
]

_FILE_KEYS = {f["key"] for g in SETTINGS_FORM_GROUPS for f in g["fields"]}


def _load_config_json_settings() -> dict[str, Any]:
    """Optional {"streamers": [...], "settings": {...}} in CONFIG_PATH — used as fallback below web_settings.json."""
    path = Path(CONFIG_PATH).expanduser().resolve()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        if isinstance(data, dict) and isinstance(data.get("settings"), dict):
            return dict(data["settings"])
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return {}


def _load_file_settings() -> dict[str, Any]:
    global _file_settings
    fallback = _load_config_json_settings()
    primary: dict[str, Any] = {}
    if WEB_SETTINGS_PATH.is_file():
        try:
            with open(WEB_SETTINGS_PATH, encoding="utf-8") as fp:
                data = json.load(fp)
            primary = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            primary = {}
    _file_settings = {**fallback, **primary}
    return _file_settings


def _env_set(name: str) -> bool:
    return name in os.environ


def _file_val(key: str) -> Any | None:
    if key not in _file_settings:
        return None
    return _file_settings[key]


def _pick_str(env_key: str, py_key: str, default: str) -> str:
    if _env_set(env_key):
        return env.str(env_key, default=default).strip()
    v = _file_val(py_key)
    if v is None:
        return default
    return str(v).strip()


def _pick_optional_str(env_key: str, py_key: str, default: str | None) -> str | None:
    if _env_set(env_key):
        raw = env.str(env_key, default="")
        return None if raw in ("", "None") else raw
    v = _file_val(py_key)
    if v is None or v == "":
        return default
    return str(v)


def _pick_int(env_key: str, py_key: str, default: int) -> int:
    if _env_set(env_key):
        return env.int(env_key, default=default)
    v = _file_val(py_key)
    if v is None or v == "":
        return default
    return int(v)


def _pick_float(env_key: str, py_key: str, default: float) -> float:
    if _env_set(env_key):
        return float(env.float(env_key, default=default))
    v = _file_val(py_key)
    if v is None or v == "":
        return default
    return float(v)


def _pick_bool(env_key: str, py_key: str, default: bool) -> bool:
    if _env_set(env_key):
        return env.bool(env_key, default=default)
    v = _file_val(py_key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes", "on")


def _rebuild_proxy_env(http_proxy: str, no_proxy: str) -> dict:
    proxies: dict = {}
    if http_proxy:
        proxies["http"] = http_proxy
        proxies["https"] = http_proxy
    for key in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        os.environ.pop(key, None)
    if http_proxy:
        os.environ["HTTP_PROXY"] = http_proxy
        os.environ["http_proxy"] = http_proxy
        os.environ["HTTPS_PROXY"] = http_proxy
        os.environ["https_proxy"] = http_proxy
    if no_proxy:
        os.environ["NO_PROXY"] = no_proxy
        os.environ["no_proxy"] = no_proxy
    return proxies


def apply_runtime_settings() -> None:
    """Load web_settings.json and refresh all module-level settings (except fixed path/bind keys)."""
    global DOWNLOADS_DIR, DATABASE_URL, MIN_FREE_DISK_PERCENT, DEBUG
    global HTTP_USER_AGENT, CHB_PROXY_TEST_URL, CHB_CF_CLEARANCE, CHB_USER_AGENT
    global REQUESTS_HTTP_PROXY, REQUESTS_NO_PROXY, REQUESTS_PROXIES
    global FFMPEG_PATH, WANTED_RESOLUTION, WANTED_RESOLUTION_PREFERENCE, CONTAINER
    global VR_FORMAT_SUFFIX, FFMPEG_READRATE, SEGMENT_TIME
    global WEBSERVER_HOST, WEBSERVER_PORT, WEBSERVER_SKIN
    global WEB_LIST_FREQUENCY, WEB_STATUS_FREQUENCY, WEB_THEATER_MODE, WEB_CONFIRM_DELETES, WEBSERVER_PASSWORD

    DOWNLOADS_DIR = env.str("STRMNTR_DOWNLOAD_DIR", "downloads")
    DATABASE_URL = env.str(
        "STRMNTR_DATABASE_URL",
        f"sqlite:///{_default_sqlite_path.as_posix()}",
    )
    WEBSERVER_HOST = env.str("STRMNTR_HOST", "127.0.0.1")
    WEBSERVER_PORT = env.int("STRMNTR_PORT", 5000)
    WEBSERVER_SKIN = env.str("STRMNTR_SKIN", "truck-kun")

    MIN_FREE_DISK_PERCENT = _pick_float("STRMNTR_MIN_FREE_SPACE", "MIN_FREE_DISK_PERCENT", 5.0)
    DEBUG = _pick_bool("STRMNTR_DEBUG", "DEBUG", False)
    HTTP_USER_AGENT = _pick_str(
        "STRMNTR_USER_AGENT",
        "HTTP_USER_AGENT",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    )
    CHB_PROXY_TEST_URL = _pick_str(
        "STRMNTR_CB_PROXY_TEST_URL",
        "CHB_PROXY_TEST_URL",
        "https://api.ipify.org?format=json",
    )
    CHB_CF_CLEARANCE = _pick_str("STRMNTR_CB_CF_CLEARANCE", "CHB_CF_CLEARANCE", "")
    CHB_USER_AGENT = _pick_str("STRMNTR_CB_USER_AGENT", "CHB_USER_AGENT", "")
    REQUESTS_HTTP_PROXY = _pick_str("STRMNTR_HTTP_PROXY", "REQUESTS_HTTP_PROXY", "")
    REQUESTS_NO_PROXY = _pick_str("STRMNTR_NO_PROXY", "REQUESTS_NO_PROXY", "")
    REQUESTS_PROXIES = _rebuild_proxy_env(REQUESTS_HTTP_PROXY, REQUESTS_NO_PROXY)

    FFMPEG_PATH = _pick_str("STRMNTR_FFMPEG_PATH", "FFMPEG_PATH", "ffmpeg")
    WANTED_RESOLUTION = _pick_int("STRMNTR_RESOLUTION", "WANTED_RESOLUTION", 1080)
    WANTED_RESOLUTION_PREFERENCE = _pick_str(
        "STRMNTR_RESOLUTION_PREF",
        "WANTED_RESOLUTION_PREFERENCE",
        "closest",
    )
    if WANTED_RESOLUTION_PREFERENCE not in RESOLUTION_PREF_CHOICES:
        WANTED_RESOLUTION_PREFERENCE = "closest"
    CONTAINER = _pick_str("STRMNTR_CONTAINER", "CONTAINER", "mp4")
    VR_FORMAT_SUFFIX = _pick_bool("STRMNTR_VR_FORMAT_SUFFIX", "VR_FORMAT_SUFFIX", True)
    FFMPEG_READRATE = _pick_float("STRMNTR_FFMPEG_READRATE", "FFMPEG_READRATE", 1.3)
    SEGMENT_TIME = _pick_optional_str("STRMNTR_SEGMENT_TIME", "SEGMENT_TIME", None)

    WEB_LIST_FREQUENCY = _pick_int("STRMNTR_LIST_FREQ", "WEB_LIST_FREQUENCY", 30)
    WEB_STATUS_FREQUENCY = _pick_int("STRMNTR_STATUS_FREQ", "WEB_STATUS_FREQUENCY", 5)
    WEB_THEATER_MODE = _pick_bool("STRMNTR_THEATER_MODE", "WEB_THEATER_MODE", False)
    WEB_CONFIRM_DELETES = _pick_str("STRMNTR_CONFIRM_DEL", "WEB_CONFIRM_DELETES", "MOBILE")
    WEBSERVER_PASSWORD = _pick_str("STRMNTR_PASSWORD", "WEBSERVER_PASSWORD", "admin")


def reload_runtime_settings() -> None:
    _load_file_settings()
    apply_runtime_settings()


def settings_form_context() -> list[dict[str, Any]]:
    """Field specs plus value, locked (env overrides file)."""
    mod = sys.modules[__name__]
    groups_out = []
    for group in SETTINGS_FORM_GROUPS:
        fields_out = []
        for field in group["fields"]:
            key = field["key"]
            env_key = field["env"]
            locked = _env_set(env_key)
            val = getattr(mod, key)
            if field["type"] == "password":
                display = ""
            elif val is None:
                display = ""
            else:
                display = val
            fields_out.append({**field, "value": display, "locked": locked})
        groups_out.append({"title": group["title"], "fields": fields_out})
    return groups_out


def save_settings_from_form(form: Any) -> tuple[bool, str]:
    """Merge POSTed values into web_settings.json. Env-set keys are skipped."""
    reload_runtime_settings()
    new_file = dict(_file_settings)
    for group in SETTINGS_FORM_GROUPS:
        for field in group["fields"]:
            key = field["env"]
            py_key = field["key"]
            if _env_set(key):
                continue
            ftype = field["type"]
            raw = form.get(py_key)
            if raw is None:
                raw = ""
            if ftype == "int":
                try:
                    new_file[py_key] = int(str(raw).strip())
                except ValueError:
                    return False, f"Invalid integer: {py_key}"
            elif ftype == "float":
                try:
                    new_file[py_key] = float(str(raw).strip())
                except ValueError:
                    return False, f"Invalid number: {py_key}"
            elif ftype == "bool":
                new_file[py_key] = str(raw).lower() in ("1", "true", "yes", "on")
            elif ftype == "optional_str":
                s = str(raw).strip()
                new_file[py_key] = None if s == "" else s
            elif ftype == "password":
                if str(form.get("WEBSERVER_PASSWORD_CLEAR", "")).lower() in ("1", "true", "on", "yes"):
                    new_file[py_key] = ""
                elif str(raw).strip() != "":
                    new_file[py_key] = str(raw)
            elif ftype == "choice":
                v = str(raw).strip()
                if v not in field.get("choices", ()):
                    return False, f"Invalid choice for {py_key}"
                new_file[py_key] = v
            else:
                new_file[py_key] = str(raw).strip()

    try:
        WEB_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(WEB_SETTINGS_PATH, "w", encoding="utf-8") as fp:
            json.dump({k: new_file[k] for k in sorted(new_file) if k in _FILE_KEYS}, fp, indent=2)
    except OSError as e:
        return False, str(e)
    reload_runtime_settings()
    return True, "Saved"


_load_file_settings()
apply_runtime_settings()
