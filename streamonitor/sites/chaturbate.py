import re
from urllib.parse import urljoin

import m3u8
import requests

import parameters
from streamonitor.bot import Bot
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
        self._proxy_test_logged = False
        self._cb_listing_meta = {}

        if parameters.CHB_USER_AGENT:
            self.session.headers["User-Agent"] = parameters.CHB_USER_AGENT

        if parameters.CHB_CF_CLEARANCE:
            self.session.cookies.set(
                "cf_clearance",
                parameters.CHB_CF_CLEARANCE,
                domain=".chaturbate.com",
                path="/",
            )

    def getWebsiteURL(self):
        return "https://www.chaturbate.com/" + self.username

    def getVideoUrl(self):
        if self.bulk_update:
            self.getStatus()
        url = self.lastInfo["url"]
        if not url:
            return None

        if "llhls.m3u8" in url:
            return self._getCmafPlaylist(url)

        if self.lastInfo.get("cmaf_edge"):
            url = url.replace("playlist.m3u8", "playlist_sfm4s.m3u8")
            url = re.sub("live-.+amlst", "live-c-fhls/amlst", url)

        return self.getWantedResolutionPlaylist(url)

    def _getCmafPlaylist(self, url):
        result = self.session.get(url, headers=self.headers)
        master = m3u8.loads(result.text)

        audio_uris = {}
        for media in master.media:
            if media.type == "AUDIO":
                audio_uris[media.group_id] = urljoin(url, media.uri)

        variants = []
        for playlist in master.playlists:
            stream_info = playlist.stream_info
            resolution = (
                stream_info.resolution
                if type(stream_info.resolution) is tuple
                else (0, 0)
            )
            audio_group = getattr(stream_info, "audio", None)
            audio_url = audio_uris.get(audio_group) if audio_group else None
            variants.append(
                {
                    "url": urljoin(url, playlist.uri),
                    "resolution": resolution,
                    "bandwidth": stream_info.bandwidth,
                    "audio_url": audio_url,
                }
            )

        if not variants:
            return url

        for variant in variants:
            w, h = variant["resolution"]
            if w < h:
                variant["resolution_diff"] = w - parameters.WANTED_RESOLUTION
            else:
                variant["resolution_diff"] = h - parameters.WANTED_RESOLUTION

        variants.sort(key=lambda a: abs(a["resolution_diff"]))

        if parameters.WANTED_RESOLUTION_PREFERENCE == "exact":
            selected = next(
                (v for v in variants if abs(v["resolution_diff"]) == 0), variants[0]
            )
        else:
            selected = variants[0]

        self.logger.info(
            f"Selected {selected['resolution'][0]}x{selected['resolution'][1]} resolution (CMAF)"
        )
        if selected["audio_url"]:
            return (selected["url"], selected["audio_url"])
        return selected["url"]

    @staticmethod
    def _parseStatus(status):
        if status == "public":
            return Status.PUBLIC
        elif status in ["private", "hidden"]:
            return Status.PRIVATE
        else:
            return Status.OFFLINE

    def _log_proxy_test(self):
        if self._proxy_test_logged:
            return

        self._proxy_test_logged = True
        try:
            r = self.session.get(parameters.CHB_PROXY_TEST_URL, timeout=10)
            self.logger.debug(
                "Chaturbate proxy test: proxies=%s user-agent=%s cf_clearance=%s status=%s body=%s",
                self.session.proxies,
                self.session.headers.get("User-Agent"),
                bool(self.session.cookies.get("cf_clearance")),
                r.status_code,
                r.text[:500],
            )
        except Exception as e:
            self.logger.debug(
                "Chaturbate proxy test failed: proxies=%s user-agent=%s cf_clearance=%s error=%s",
                self.session.proxies,
                self.session.headers.get("User-Agent"),
                bool(self.session.cookies.get("cf_clearance")),
                e,
            )

    def getStatus(self):
        headers = {"X-Requested-With": "XMLHttpRequest"}
        data = {"room_slug": self.username, "bandwidth": "high"}

        try:
            self._log_proxy_test()
            r = self.session.post(
                "https://chaturbate.com/get_edge_hls_url_ajax/",
                headers=headers,
                data=data,
            )
            self.logger.debug(
                "get_edge_hls_url_ajax response: status=%s content-type=%s body=%s",
                r.status_code,
                r.headers.get("Content-Type"),
                r.text[:1000],
            )
            self.lastInfo = r.json()
            status = self._parseStatus(self.lastInfo["room_status"])
            if status == Status.PUBLIC and not self.lastInfo["url"]:
                status = Status.RESTRICTED
        except Exception:
            status = Status.RATELIMIT

        self.ratelimit = status == Status.RATELIMIT
        return status

    @staticmethod
    def _apply_affiliate_listing_meta(streamer, model_data):
        meta = {}
        rs = model_data.get("room_subject")
        if rs:
            s = str(rs).strip().replace("\n", " ")
            if len(s) > 160:
                s = s[:157] + "..."
            meta["room_subject"] = s
        if model_data.get("num_users") is not None:
            meta["num_users"] = str(model_data["num_users"])
        loc = model_data.get("location")
        if loc:
            sl = str(loc).strip()
            if len(sl) > 60:
                sl = sl[:57] + "..."
            meta["location"] = sl
        tags = model_data.get("tags")
        if isinstance(tags, list) and tags:
            meta["tags"] = ", ".join(str(t) for t in tags[:10])
        streamer._cb_listing_meta = meta

    def web_ui_rows(self, include_last_recording=True):
        rows = list(super().web_ui_rows(include_last_recording=include_last_recording))
        m = getattr(self, "_cb_listing_meta", None) or {}
        if m.get("room_subject"):
            rows.append(("Room", m["room_subject"]))
        if m.get("num_users"):
            rows.append(("Viewers", m["num_users"]))
        if m.get("location"):
            rows.append(("Location", m["location"]))
        if m.get("tags"):
            rows.append(("Tags", m["tags"]))
        return tuple(rows)

    @classmethod
    def getStatusBulk(cls, streamers):
        for streamer in streamers:
            if not isinstance(streamer, Chaturbate):
                continue

        session = requests.Session()
        session.headers.update(cls.active_request_headers())
        if parameters.REQUESTS_PROXIES:
            session.proxies.update(parameters.REQUESTS_PROXIES)
        r = session.get(
            "https://chaturbate.com/affiliates/api/onlinerooms/?format=json&wm=DkfRj",
            timeout=10,
        )

        try:
            data = r.json()
        except requests.exceptions.JSONDecodeError:
            print("Failed to parse JSON response")
            return
        data_map = {str(model["username"]).lower(): model for model in data}

        for streamer in streamers:
            model_data = data_map.get(streamer.username.lower())
            if not model_data:
                streamer.setStatus(Status.OFFLINE)
                streamer._cb_listing_meta = {}
                continue
            cls._apply_affiliate_listing_meta(streamer, model_data)
            if model_data.get("gender"):
                streamer.gender = cls._GENDER_MAP.get(model_data.get("gender"))
            if model_data.get("country"):
                streamer.country = model_data.get("country", "").upper()
            status = cls._parseStatus(model_data["current_show"])
            if status == Status.PUBLIC:
                if streamer.sc in [Status.PUBLIC, Status.RESTRICTED]:
                    continue
                status = streamer.getStatus()
            if status == Status.UNKNOWN:
                print(
                    f"[{streamer.siteslug}] {streamer.username}: Bulk update got unknown status: {status}"
                )
            streamer.setStatus(status)
