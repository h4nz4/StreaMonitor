import os
import subprocess
from urllib.parse import urljoin
from time import sleep

import m3u8

from parameters import CONTAINER, FFMPEG_PATH


def _remux_concat_file(ffmpeg_executable, src_path, dest_path, logger):
    """Stream-copy remux of raw concat; retries with options that often fix fMP4 HLS."""
    src_path = os.path.abspath(src_path)
    dest_path = os.path.abspath(dest_path)
    out_ext = os.path.splitext(dest_path)[1].lower()
    out_fmt = "mpegts" if out_ext == ".ts" else "mp4"

    def out_tail():
        return ["-c", "copy", "-f", out_fmt, dest_path]

    base_cmd = [
        ffmpeg_executable,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    attempts = [
        base_cmd + ["-i", src_path] + out_tail(),
        base_cmd + ["-fflags", "+genpts+igndts", "-i", src_path] + out_tail(),
        base_cmd
        + [
            "-probesize",
            "100M",
            "-analyzeduration",
            "100M",
            "-i",
            src_path,
        ]
        + out_tail(),
        base_cmd + ["-f", "mp4", "-i", src_path] + out_tail(),
        base_cmd
        + [
            "-err_detect",
            "ignore_err",
            "-fflags",
            "+genpts+igndts",
            "-i",
            src_path,
        ]
        + out_tail(),
    ]

    last_err = ""
    for cmd in attempts:
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        r = subprocess.run(cmd, capture_output=True)
        last_err = (r.stderr or b"").decode(errors="replace").strip()
        if r.returncode in (0, 255) and os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
            return True, ""
        if last_err:
            logger.debug(
                "ffmpeg remux attempt exit %s: %s",
                r.returncode,
                last_err[-2000:],
            )
    return False, last_err


def getVideoPythonHLS(self, url, filename):
    self.logger.debug(f"getVideoPythonHLS called with url={url} filename={filename}")

    video_url = url
    audio_url = None
    if isinstance(url, tuple):
        video_url, audio_url = url

    session = self.session
    headers = self.headers.copy()
    cookies = self.cookies

    tmpfilename = filename[: -len("." + CONTAINER)] + ".tmp.hls"
    downloaded = set()
    key_cache = {}
    wrote_fmp4_init = False

    self.logger.debug(f"Session type: {type(session).__name__}")
    self.logger.debug(f"Cookies: {list(cookies) if cookies else None}")

    def abs_url(parent_url, child_url):
        if not child_url:
            return None
        if child_url.startswith("http"):
            return child_url
        return urljoin(parent_url, child_url)

    def parse_byterange(spec):
        if not spec:
            return None
        spec = str(spec).strip()
        if "@" in spec:
            length_s, offset_s = spec.split("@", 1)
            return int(offset_s), int(length_s)
        return 0, int(spec)

    def fetch_playlist(target_url):
        self.logger.debug(f"Fetching playlist: {target_url}")
        r = session.get(target_url, headers=headers, cookies=cookies)
        self.log_response_debug(r, "getVideoPythonHLS")
        if r.status_code != 200:
            self.logger.error(
                f"Playlist fetch failed: HTTP {r.status_code} for {target_url}"
            )
            return None
        playlist = m3u8.loads(r.text, uri=target_url)
        self.logger.debug(
            f"Parsed playlist: is_variant={playlist.is_variant}, "
            f"variants={len(playlist.playlists)}, segments={len(playlist.segments)}"
        )
        return playlist

    def fetch_bytes(target_url, byterange_spec=None):
        self.logger.debug(f"Fetching segment: {target_url}")
        req_headers = headers.copy()
        br = parse_byterange(byterange_spec)
        if br:
            offset, length = br
            end = offset + length - 1
            req_headers["Range"] = f"bytes={offset}-{end}"
        r = session.get(target_url, headers=req_headers, cookies=cookies)
        if r.status_code not in (200, 206):
            self.logger.error(
                f"Segment fetch failed: HTTP {r.status_code} for {target_url}"
            )
            return None
        self.logger.debug(f"Segment OK: {len(r.content)} bytes")
        return r.content

    def key_url(key_obj):
        if not key_obj or not key_obj.uri:
            return None
        try:
            u = key_obj.absolute_uri
            if u:
                return u
        except ValueError:
            pass
        return abs_url(video_url, key_obj.uri)

    def aes_iv(key_obj, sequence_number):
        if key_obj.iv:
            hex_str = key_obj.iv.strip().lower()
            if hex_str.startswith("0x"):
                hex_str = hex_str[2:]
            return bytes.fromhex(hex_str)
        seq = sequence_number if sequence_number is not None else 0
        return seq.to_bytes(16, "big")

    def decrypt_aes_if_needed(data, key_obj, sequence_number):
        if not key_obj or (key_obj.method or "").upper() == "NONE":
            return data
        if (key_obj.method or "").upper() != "AES-128":
            self.logger.error(
                f"Unsupported EXT-X-KEY method {key_obj.method!r}; use ffmpeg downloader."
            )
            return None
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
        except ImportError:
            self.logger.error(
                "Encrypted stream requires pycryptodome (pip install pycryptodome)."
            )
            return None
        ku = key_url(key_obj)
        if not ku:
            return None
        if ku not in key_cache:
            kr = session.get(ku, headers=headers, cookies=cookies)
            if kr.status_code != 200 or len(kr.content) != 16:
                self.logger.error(f"Key fetch failed: HTTP {kr.status_code} for {ku}")
                return None
            key_cache[ku] = kr.content
        key_bytes = key_cache[ku]
        iv = aes_iv(key_obj, sequence_number)
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
        plain = cipher.decrypt(data)
        try:
            return unpad(plain, AES.block_size)
        except ValueError:
            return plain

    def write_init_section(init, progress):
        nonlocal wrote_fmp4_init
        if not init or not init.uri:
            return True
        dedup = ("init", init.uri, init.byterange or "")
        if dedup in downloaded:
            return True
        target = init.absolute_uri or abs_url(video_url, init.uri)
        if not target:
            return False
        raw = fetch_bytes(target, init.byterange)
        if raw is None:
            return False
        outfile.write(raw)
        downloaded.add(dedup)
        wrote_fmp4_init = True
        progress[0] = True
        return True

    def write_media(uri, byterange_spec, key_obj, seq_for_iv, progress):
        if not uri:
            return True
        dedup = ("media", uri, str(byterange_spec or ""), seq_for_iv)
        if dedup in downloaded:
            return True
        target = abs_url(video_url, uri)
        if not target:
            return False
        raw = fetch_bytes(target, byterange_spec)
        if raw is None:
            return False
        payload = decrypt_aes_if_needed(raw, key_obj, seq_for_iv)
        if payload is None:
            return False
        outfile.write(payload)
        downloaded.add(dedup)
        progress[0] = True
        return True

    def iter_segment_writes(segment, progress):
        if segment.init_section:
            if not write_init_section(segment.init_section, progress):
                yield False
                return
        base_seq = segment.media_sequence
        if segment.parts:
            for part_index, part in enumerate(segment.parts):
                if part.gap or not part.uri:
                    continue
                iv_seq = (base_seq or 0) + part_index
                ok = write_media(
                    part.uri, part.byterange, segment.key, iv_seq, progress
                )
                yield ok
                if not ok:
                    return
            return
        if segment.uri:
            ok = write_media(
                segment.uri,
                segment.byterange,
                segment.key,
                base_seq or 0,
                progress,
            )
            yield ok

    def resolve_media(target_url):
        playlist = fetch_playlist(target_url)
        if playlist is None:
            return None
        if not playlist.is_variant:
            self.logger.debug(
                "Master URL points to a non-variant playlist, using as-is"
            )
            return target_url, None, playlist
        sources = []
        for playlist_item in playlist.playlists:
            stream_info = playlist_item.stream_info
            resolution = (
                stream_info.resolution
                if isinstance(stream_info.resolution, tuple)
                else (0, 0)
            )
            sources.append(
                {
                    "url": playlist_item.uri,
                    "resolution": resolution,
                    "audio": getattr(stream_info, "audio", None),
                }
            )
            self.logger.debug(
                f"Variant: {playlist_item.uri} res={resolution} audio_group={getattr(stream_info, 'audio', None)}"
            )
        if not sources:
            self.logger.error("No variant sources found in master playlist")
            return None
        sources.sort(key=lambda item: abs(item["resolution"][1] - 720))
        selected = sources[0]
        self.logger.debug(f"Selected variant: {selected}")
        resolved_video = abs_url(target_url, selected["url"])
        resolved_audio = None
        if selected["audio"] and playlist.media:
            for media in playlist.media:
                self.logger.debug(
                    f"Media entry: type={media.type}, group_id={media.group_id} uri={media.uri}"
                )
                if media.type == "AUDIO" and media.group_id == selected["audio"]:
                    resolved_audio = abs_url(target_url, media.uri)
                    self.logger.debug(f"Matched audio: {resolved_audio}")
                    break
        return resolved_video, resolved_audio, playlist

    resolved = resolve_media(video_url)
    if not resolved:
        self.logger.error("resolve_media returned None, cannot start download")
        return False
    video_url, audio_url, _master_playlist = resolved

    self.logger.debug(f"Python HLS video input: {video_url}")
    if audio_url:
        self.logger.debug(
            "Python HLS audio input: %s (video-only recording; use ffmpeg for muxed A+V)",
            audio_url,
        )

    self.stopDownloadFlag = False

    def terminate():
        self.stopDownloadFlag = True

    self.stopDownload = terminate
    try:
        with open(tmpfilename, "wb") as outfile:
            self.logger.debug(f"Opened tmp file: {tmpfilename}")
            while not self.stopDownloadFlag:
                playlist = fetch_playlist(video_url)
                if playlist is None:
                    return False
                if len(playlist.segments) == 0:
                    self.logger.debug("Playlist has no segments yet, sleeping 1s")
                    sleep(1)
                    continue

                progress = [False]
                for init in playlist.segment_map:
                    if init and init.uri:
                        if not write_init_section(init, progress):
                            return False

                for segment in playlist.segments:
                    for result in iter_segment_writes(segment, progress):
                        if not result:
                            return False

                if not progress[0]:
                    sleep(1)

        if not os.path.exists(tmpfilename) or os.path.getsize(tmpfilename) == 0:
            if os.path.exists(tmpfilename):
                os.remove(tmpfilename)
            self.logger.error("No data was downloaded")
            return False

        base = os.path.splitext(filename)[0]
        final_ext = ".mp4" if wrote_fmp4_init else ".ts"
        final_path = base + final_ext
        # Temp must end in .mp4 / .ts so ffmpeg can infer (or match) the muxer.
        remux_tmp = base + ".remux-temp" + final_ext
        if os.path.exists(remux_tmp):
            os.remove(remux_tmp)

        ok, err_txt = _remux_concat_file(
            FFMPEG_PATH, tmpfilename, remux_tmp, self.logger
        )
        if not ok:
            self.logger.error(
                "ffmpeg remux failed after retries; saving concat without remux. stderr:\n%s",
                err_txt[-4000:] if err_txt else "(empty)",
            )
            if os.path.exists(remux_tmp):
                os.remove(remux_tmp)
            if os.path.exists(final_path):
                os.remove(final_path)
            os.replace(tmpfilename, final_path)
            self.logger.info(f"Saved recording to {final_path} (unmuxed)")
            return True

        os.remove(tmpfilename)
        if os.path.exists(final_path):
            os.remove(final_path)
        os.replace(remux_tmp, final_path)
        self.logger.info(f"Saved recording to {final_path}")
        return True
    finally:
        self.stopDownload = None
