import re
from urllib.parse import urljoin

import m3u8
import requests

from parameters import CAPTURE_TS, USE_CLOUDSCRAPER
from streamonitor.bot import Bot
from streamonitor.http_session import create_http_session
from streamonitor.enums import Gender, Status


class Chaturbate(Bot):
    site = "Chaturbate"
    siteslug = "CB"
    bulk_update = True

    _GENDER_MAP = {
        "f": Gender.FEMALE,
        "m": Gender.MALE,
        "s": Gender.TRANS,
        "c": Gender.BOTH,
    }

    def __init__(self, username):
        super().__init__(username)
        self.sleep_on_offline = 30
        self.sleep_on_error = 60

    def getWebsiteURL(self):
        return "https://www.chaturbate.com/" + self.username

    def getVideoUrl(self):
        if self.bulk_update:
            self.getStatus()
        url = self.lastInfo["url"]
        if not url:
            return None

        master_res = self.session.get(url, headers=self.headers, cookies=self.cookies)
        master_m3u8 = m3u8.loads(master_res.content.decode("utf-8"))

        audio_map = {}
        if master_m3u8.media:
            for media in master_m3u8.media:
                if media.type == "AUDIO" and media.group_id:
                    audio_map[media.group_id] = media.uri

        sources = []
        for playlist in master_m3u8.playlists:
            stream_info = playlist.stream_info
            resolution = (
                stream_info.resolution
                if type(stream_info.resolution) is tuple
                else (0, 0)
            )
            audio_group = getattr(stream_info, "audio", None)
            sources.append(
                {
                    "url": playlist.uri,
                    "resolution": resolution,
                    "frame_rate": stream_info.frame_rate,
                    "bandwidth": stream_info.bandwidth,
                    "audio": audio_group,
                }
            )

        if not sources:
            self.logger.error("No available sources")
            return None

        for source in sources:
            width, height = source["resolution"]
            source["resolution_diff"] = (height - 720) ** 2

        sources.sort(key=lambda a: a["resolution_diff"])
        selected_source = sources[0]

        if selected_source["resolution"][1] != 0:
            self.logger.info(
                f"Selected {selected_source['resolution'][0]}x{selected_source['resolution'][1]} resolution"
            )

        video_url = urljoin(url, selected_source["url"])
        audio_url = None
        audio_group = selected_source.get("audio")
        if audio_group and audio_group in audio_map:
            audio_url = urljoin(url, audio_map[audio_group])

        if audio_url:
            return video_url, audio_url
        return video_url

    @staticmethod
    def _parseStatus(status):
        if status == "public":
            return Status.PUBLIC
        elif status in ["private", "hidden"]:
            return Status.PRIVATE
        else:
            return Status.OFFLINE

    def getStatus(self):
        headers = {"X-Requested-With": "XMLHttpRequest"}
        data = {"room_slug": self.username, "bandwidth": "high"}

        try:
            r = requests.post(
                "https://chaturbate.com/get_edge_hls_url_ajax/",
                headers=headers,
                data=data,
            )
            self.lastInfo = r.json()
            status = self._parseStatus(self.lastInfo["room_status"])
            if status == status.PUBLIC and not self.lastInfo["url"]:
                status = status.RESTRICTED
        except requests.exceptions.ConnectionError as e:
            self.logger.debug(f"Connection error during getStatus: {e}")
            status = Status.RATELIMIT
        except requests.exceptions.Timeout as e:
            self.logger.debug(f"Timeout during getStatus: {e}")
            status = Status.RATELIMIT
        except requests.exceptions.HTTPError as e:
            self.logger.debug(
                f"HTTP error during getStatus: {e.response.status_code} {e.response.reason}"
            )
            status = Status.RATELIMIT
        except (ValueError, KeyError) as e:
            self.logger.debug(f"Data/error parsing failed in getStatus: {e}")
            status = Status.RATELIMIT
        except Exception as e:
            self.logger.debug(f"Unexpected error in getStatus: {type(e).__name__}: {e}")
            status = Status.RATELIMIT

        self.ratelimit = status == Status.RATELIMIT
        return status

    @classmethod
    def getStatusBulk(cls, streamers, session=None):
        for streamer in streamers:
            if not isinstance(streamer, Chaturbate):
                continue

        if session is None:
            session = create_http_session(USE_CLOUDSCRAPER and cls.use_cloudscraper)
        session.headers.update(cls.headers)
        r = session.get(
            "https://chaturbate.com/affiliates/api/onlinerooms/?format=json&wm=DkfRj",
            timeout=10,
        )

        if r.status_code != 200:
            cls.logger.debug(
                f"[getStatusBulk] HTTP {r.status_code} {r.reason}: {r.text[:200]}"
            )
            return
        try:
            data = r.json()
        except requests.exceptions.JSONDecodeError:
            cls.logger.debug(f"[getStatusBulk] JSON decode error: {r.text[:200]}")
            return
        data_map = {str(model["username"]).lower(): model for model in data}

        for streamer in streamers:
            model_data = data_map.get(streamer.username.lower())
            if not model_data:
                streamer.setStatus(Status.OFFLINE)
                continue
            if model_data.get("gender"):
                streamer.gender = cls._GENDER_MAP.get(model_data.get("gender"))
            if model_data.get("country"):
                streamer.country = model_data.get("country", "").upper()
            status = cls._parseStatus(model_data["current_show"])
            if status == status.PUBLIC:
                if streamer.sc in [status.PUBLIC, Status.RESTRICTED]:
                    continue
                status = streamer.getStatus()
            if status == Status.UNKNOWN:
                print(
                    f"[{streamer.siteslug}] {streamer.username}: Bulk update got unknown status: {status}"
                )
            streamer.setStatus(status)
