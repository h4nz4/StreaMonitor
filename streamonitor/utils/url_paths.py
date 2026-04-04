from urllib.parse import urlparse, urlencode


def quote_path_segment(value) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")


def streamer_qs(username, site, **extra) -> str:
    """Build application/x-www-form-urlencoded query for username+site (+ optional keys). Safe for any characters."""
    params = {"username": str(username), "site": str(site)}
    for key, value in extra.items():
        if value is None:
            continue
        params[key] = str(value)
    return urlencode(params)


def recordings_browser_path(username, site, sort_by_size=False, play_video=None) -> str:
    q = {"username": str(username), "site": str(site)}
    if sort_by_size:
        q["sorted"] = "True"
    if play_video is not None:
        q["play_video"] = str(play_video)
    return f"/recordings?{urlencode(q)}"


def normalize_streamer_username(username: str, site: str) -> str:
    """Strip profile URLs and stray path segments so pasted links become a plain username."""
    u = (username or "").strip()
    if not u:
        return u
    if u.lower().startswith(("http://", "https://")):
        parsed = urlparse(u)
        segments = [p for p in parsed.path.split("/") if p]
        from streamonitor.bot import Bot

        site_cls = Bot.str2site(site) if site else None
        site_tokens = set()
        if site_cls:
            site_tokens.add(site_cls.site.lower())
            site_tokens.add(site_cls.siteslug.lower())
            for a in getattr(site_cls, "aliases", None) or []:
                site_tokens.add(a.lower())
        if site:
            site_tokens.add(site.lower())
        while segments and segments[-1].lower() in site_tokens:
            segments.pop()
        if segments:
            u = segments[-1]
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u.strip()
