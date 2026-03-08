from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List

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

    raw_lower = raw.lower()

    if raw_lower.startswith("socks5://"):
        return raw

    if raw_lower.startswith("socks5h://"):
        return "socks5://" + raw[len("socks5h://"):]

    if raw_lower.startswith("http://"):
        return raw

    if raw_lower.startswith("https://"):
        return raw

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


def fetch_proxy_file(url: str, timeout_seconds: float = 30.0, max_retries: int = 3) -> str:
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[proxy_loader] downloading proxy file (attempt {attempt}/{max_retries}): {url}")
            with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
                response = client.get(url, headers={"Cache-Control": "no-cache"})
                response.raise_for_status()
                text = response.text

            print(
                f"[proxy_loader] download succeeded on attempt {attempt}; "
                f"received {len(text.splitlines())} raw lines"
            )
            return text

        except Exception as exc:
            last_exc = exc
            print(f"[proxy_loader] download failed on attempt {attempt}/{max_retries}: {exc}")

            if attempt < max_retries:
                sleep_seconds = min(2 * attempt, 5)
                print(f"[proxy_loader] retrying after {sleep_seconds}s...")
                time.sleep(sleep_seconds)

    raise ProxyLoadError(f"failed to download proxy file after {max_retries} attempts: {last_exc}")


def save_proxy_cache(text: str, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    print(f"[proxy_loader] cache updated: {cache_path}")


def get_proxy_list() -> List[str]:
    proxy_file_url = os.getenv("PROXY_FILE_URL", DEFAULT_PROXY_FILE_URL)
    cache_path = Path(os.getenv("PROXY_CACHE_PATH", "data/proxiesus.txt"))
    timeout_seconds = float(os.getenv("PROXY_FILE_TIMEOUT_SECONDS", "30"))
    max_retries = int(os.getenv("PROXY_FILE_MAX_RETRIES", "3"))

    print(f"[proxy_loader] force refresh from remote: {proxy_file_url}")
    text = fetch_proxy_file(
        url=proxy_file_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )

    save_proxy_cache(text, cache_path)

    proxies = load_proxies_from_text(text)
    if not proxies:
        raise ProxyLoadError("proxy file downloaded successfully but no valid proxies were found")

    print(f"[proxy_loader] loaded {len(proxies)} valid proxies from latest remote file")
    return proxies
