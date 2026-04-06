from streamonitor.bot import Bot
from streamonitor.downloaders.hls_python import getVideoPythonHLS
from streamonitor.enums import Status


class CamSoda(Bot):
    site = "CamSoda"
    siteslug = "CS"

    def getWebsiteURL(self):
        return "https://www.camsoda.com/" + self.username

    getVideo = getVideoPythonHLS

    def getVideoUrl(self):
        track_params = "filter=tracks:v4v3v2v1a1a2&multitrack=true"
        server = self.lastInfo["stream"]["edge_servers"][0]
        stream_name = self.lastInfo["stream"]["stream_name"]
        token = self.lastInfo["stream"]["token"]
        url = f"https://{server}/{stream_name}_v1/index.ll.m3u8?{track_params}&token={token}"
        self.logger.debug(f"Master playlist URL: {url}")
        return self.getWantedResolutionPlaylist(url)

    def getStatus(self):
        try:
            r = self.session.get(
                "https://www.camsoda.com/api/v1/chat/react/" + self.username,
                headers=self.headers,
            )
        except Exception as e:
            self.handle_status_error(e, "getStatus")
            return Status.UNKNOWN
        if r.status_code == 403:
            self.log_response_debug(r, "getStatus")
            return Status.RATELIMIT
        if r.status_code != 200:
            self.log_response_debug(r, "getStatus")
            return Status.UNKNOWN

        self.lastInfo = r.json()

        if "error" in self.lastInfo and self.lastInfo["error"] == "No username found.":
            return Status.NOTEXIST
        if "stream" not in self.lastInfo:
            return Status.UNKNOWN

        stream_data = self.lastInfo["stream"]
        if "edge_servers" in stream_data and len(stream_data["edge_servers"]) > 0:
            return Status.PUBLIC
        if "private_servers" in stream_data and len(stream_data["private_servers"]) > 0:
            return Status.PRIVATE
        if "token" in stream_data:
            return Status.OFFLINE
        return Status.UNKNOWN
