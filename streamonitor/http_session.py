"""Factory for HTTP clients (plain requests vs cloudscraper)."""

from __future__ import annotations

import requests


def create_http_session(use_cloudscraper: bool) -> requests.Session:
    if use_cloudscraper:
        import cloudscraper

        return cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    return requests.Session()
