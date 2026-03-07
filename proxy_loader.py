from __future__ import annotations

from pathlib import Path
from typing import List
import os

import httpx

DEFAULT_PROXY_FILE_URL = (
    "https://raw.githubusercontent.com/jianming18/proxiesus-updater/main/proxiesus.txt"
)


class ProxyLoadError(RuntimeError):
    pass


def normalize_proxy_line(line: str) -> str | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    if raw.startswith(("socks5://", "socks5h://")):
        return raw.replace("socks5h://", "socks5://", 1)

    return f"socks5://{raw}"


def load_proxies_from_text(text: str) -> List[str]:
    proxies: List[str] = []
    seen: set[str] = set()

    for line in text.splitlines():
        proxy = normalize_proxy_line(line)
        if proxy and proxy not in seen:
            seen.add(proxy)
            proxies.append(proxy)

    return proxies


def fetch_proxy_file(url: str, timeout_seconds: float = 30.0) -> str:
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def save_proxy_cache(text: str, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")


def load_proxy_cache(cache_path: Path) -> str:
    if not cache_path.exists():
        raise ProxyLoadError(f"proxy cache not found: {cache_path}")
    return cache_path.read_text(encoding="utf-8")


def get_proxy_list() -> List[str]:
    proxy_file_url = os.getenv("PROXY_FILE_URL", DEFAULT_PROXY_FILE_URL)
    cache_path = Path(os.getenv("PROXY_CACHE_PATH", "data/proxiesus.txt"))
    allow_cache_fallback = os.getenv("PROXY_CACHE_FALLBACK", "1") == "1"

    text: str | None = None
    errors: list[str] = []

    try:
        text = fetch_proxy_file(proxy_file_url)
        save_proxy_cache(text, cache_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"download failed: {exc}")
        if allow_cache_fallback:
            try:
                text = load_proxy_cache(cache_path)
            except Exception as cache_exc:  # noqa: BLE001
                errors.append(f"cache failed: {cache_exc}")

    if text is None:
        raise ProxyLoadError("; ".join(errors) or "unable to load proxy file")

    proxies = load_proxies_from_text(text)
    if not proxies:
        raise ProxyLoadError("proxy file was loaded but no valid proxies were found")

    return proxies
