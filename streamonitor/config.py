import json
import os
import sys
import time

from parameters import CONFIG_PATH
from streamonitor.bot import Bot
from streamonitor.log import Logger

logger = Logger('[CONFIG]').get_logger()
config_loc = CONFIG_PATH


def _reject_config_dir(path: str) -> None:
    if os.path.exists(path) and os.path.isdir(path):
        logger.error(
            f"Config path {path!r} is a directory. If you use Docker, binding a host path to a "
            "single file that does not exist makes Docker create a *directory* with that name on "
            "the host. Remove that path on the host, bind-mount a directory instead, and set "
            "STRMNTR_CONFIG to a file inside it (e.g. /app/data/config.json)."
        )
        sys.exit(1)


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _streamer_list_from_doc(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        s = data.get("streamers")
        if isinstance(s, list):
            return s
    return []


def load_config():
    _reject_config_dir(config_loc)
    try:
        with open(config_loc, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _streamer_list_from_doc(data)
    except FileNotFoundError:
        _ensure_parent_dir(config_loc)
        with open(config_loc, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)
        return []
    except Exception as e:
        print(e)
        sys.exit(1)


def save_config(config):
    _reject_config_dir(config_loc)
    try:
        _ensure_parent_dir(config_loc)
        use_wrapper = False
        preserved_settings = {}
        if os.path.isfile(config_loc):
            try:
                with open(config_loc, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict) and ("streamers" in raw or "settings" in raw):
                    use_wrapper = True
                    ps = raw.get("settings")
                    if isinstance(ps, dict):
                        preserved_settings = ps
            except (json.JSONDecodeError, OSError):
                pass
        with open(config_loc, "w", encoding="utf-8") as f:
            if use_wrapper:
                json.dump({"streamers": config, "settings": preserved_settings}, f, indent=4)
            else:
                json.dump(config, f, indent=4)

        return True
    except Exception as e:
        print(e)
        sys.exit(1)


def loadStreamers():
    streamers = []
    for streamer in load_config():
        username = streamer["username"]
        site = streamer["site"]

        bot_class = Bot.str2site(site)
        if not bot_class:
            logger.warning(f'Unknown site: {site} (user: {username})')
            continue

        streamer_bot = bot_class.fromConfig(streamer)
        streamers.append(streamer_bot)
        streamer_bot.start()
        time.sleep(0.1)
    return streamers
