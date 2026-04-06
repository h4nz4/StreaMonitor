import errno
import os
import re
import subprocess
import sys
from datetime import datetime

import requests.cookies
from threading import Thread
from parameters import (
    DEBUG,
    SEGMENT_TIME,
    CONTAINER,
    FFMPEG_PATH,
    FFMPEG_READRATE,
    CAPTURE_TS,
)


def _get_first_program_date_time(session, url, headers):
    """Fetch an HLS playlist and return the first EXT-X-PROGRAM-DATE-TIME."""
    try:
        resp = session.get(url, headers=headers, timeout=10)
        match = re.search(r"#EXT-X-PROGRAM-DATE-TIME:(.+)", resp.text)
        if match:
            return datetime.fromisoformat(match.group(1).strip())
    except Exception:
        pass
    return None


def _compute_av_offset(session, video_url, audio_url, headers):
    """Return the seconds audio leads video based on PROGRAM-DATE-TIME tags.

    A positive value means audio content starts later in real time,
    so it needs to be delayed (via -itsoffset) to align with video.
    Returns 0.0 if the offset can't be determined.
    """
    video_pdt = _get_first_program_date_time(session, video_url, headers)
    audio_pdt = _get_first_program_date_time(session, audio_url, headers)
    if video_pdt and audio_pdt:
        return (audio_pdt - video_pdt).total_seconds()
    return 0.0


def getVideoFfmpeg(self, url, filename):
    video_url = url
    audio_url = None
    if isinstance(url, tuple):
        video_url, audio_url = url

    if hasattr(self, "logger"):
        if audio_url:
            self.logger.debug(f"FFmpeg video input: {video_url}")
            self.logger.debug(f"FFmpeg audio input: {audio_url}")
        else:
            self.logger.debug(f"FFmpeg input: {video_url}")

    cmd = [FFMPEG_PATH, "-user_agent", self.headers["User-Agent"]]

    headers_text = ""
    if hasattr(self, "headers"):
        if self.headers.get("Referer"):
            headers_text += f"Referer: {self.headers['Referer']}\r\n"
        if self.headers.get("Origin"):
            headers_text += f"Origin: {self.headers['Origin']}\r\n"
        if self.headers.get("Accept"):
            headers_text += f"Accept: {self.headers['Accept']}\r\n"
        if self.headers.get("Accept-Language"):
            headers_text += f"Accept-Language: {self.headers['Accept-Language']}\r\n"
    if headers_text:
        cmd.extend(["-headers", headers_text])

    if hasattr(self, "cookies") and self.cookies is not None:
        cookie_header = "; ".join(
            f"{cookie.name}={cookie.value}" for cookie in self.cookies
        )
        if cookie_header:
            if hasattr(self, "logger"):
                self.logger.debug(f"FFmpeg cookies: {cookie_header}")
            cmd.extend(["-cookies", cookie_header])

    if FFMPEG_READRATE:
        cmd.extend(["-readrate", f"{FFMPEG_READRATE!s}"])

    hls_opts = ["-max_reload", "20", "-seg_max_retry", "20", "-m3u8_hold_counters", "20"]

    if audio_url:
        av_offset = _compute_av_offset(self.session, video_url, audio_url, self.headers)
        if hasattr(self, "logger"):
            self.logger.debug(f"A/V offset from PROGRAM-DATE-TIME: {av_offset:.3f}s")

        if av_offset > 0:
            cmd.extend(["-thread_queue_size", "64"])
            cmd.extend(hls_opts + ["-i", video_url])
            cmd.extend(["-itsoffset", f"{av_offset:.3f}", "-thread_queue_size", "64"])
            cmd.extend(["-i", audio_url])
        elif av_offset < 0:
            cmd.extend(["-itsoffset", f"{-av_offset:.3f}", "-thread_queue_size", "64"])
            cmd.extend(hls_opts + ["-i", video_url])
            cmd.extend(["-thread_queue_size", "64"])
            cmd.extend(["-i", audio_url])
        else:
            cmd.extend(["-thread_queue_size", "64"])
            cmd.extend(hls_opts + ["-i", video_url])
            cmd.extend(["-thread_queue_size", "64"])
            cmd.extend(["-i", audio_url])
        cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])
    else:
        cmd.extend(hls_opts + ["-i", video_url])
        cmd.extend(["-map", "0:v?", "-map", "0:a?"])

    cmd.extend(["-c:v", "copy", "-c:a", "copy"])

    suffix = ""
    if hasattr(self, "filename_extra_suffix"):
        suffix = self.filename_extra_suffix

    # Use the bot's specific capture_ts setting
    capture_ts = getattr(
        self, "capture_ts", CAPTURE_TS if CAPTURE_TS is not None else False
    )
    if capture_ts:
        output_ext = "ts"
    else:
        output_ext = CONTAINER

    if SEGMENT_TIME is not None:
        username = filename.rsplit("-", maxsplit=2)[0]
        cmd.extend(
            [
                "-f",
                "segment",
                "-reset_timestamps",
                "1",
                "-segment_time",
                str(SEGMENT_TIME),
                "-strftime",
                "1",
            ]
        )
        cmd.extend([f"{username}-%Y%m%d-%H%M%S{suffix}.{output_ext}"])
    else:
        cmd.extend([os.path.splitext(filename)[0] + suffix + "." + output_ext])

    class _Stopper:
        def __init__(self):
            self.stop = False

        def pls_stop(self):
            self.stop = True

    stopping = _Stopper()
    error = False

    def execute():
        nonlocal error
        try:
            if DEBUG:
                self.logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            stderr = (
                open(filename + ".stderr.log", "w+") if DEBUG else subprocess.DEVNULL
            )
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                args=cmd,
                stdin=subprocess.PIPE,
                stderr=stderr,
                stdout=subprocess.DEVNULL,
                startupinfo=startupinfo,
            )
        except OSError as e:
            if e.errno == errno.ENOENT:
                self.logger.error("FFMpeg executable not found!")
                error = True
                return
            else:
                self.logger.error("Got OSError, errno: " + str(e.errno))
                error = True
                return

        while process.poll() is None:
            if stopping.stop:
                process.communicate(b"q")
                break
            try:
                process.wait(1)
            except subprocess.TimeoutExpired:
                pass

        if process.returncode and process.returncode != 0 and process.returncode != 255:
            self.logger.error(
                "The process exited with an error. Return code: "
                + str(process.returncode)
            )
            error = True
            return

    thread = Thread(target=execute)
    thread.start()
    self.stopDownload = lambda: stopping.pls_stop()
    thread.join()
    self.stopDownload = None
    return not error
