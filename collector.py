from __future__ import annotations

import asyncio
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from TikTokApi import TikTokApi

from proxy_loader import get_proxy_list


class CollectorError(RuntimeError):
    pass


@dataclass
class AttemptResult:
    proxy: str
    ok: bool
    reason: str
    items: List[Dict[str, Any]]


def deep_get(obj: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def extract_hashtags(video_dict: Dict[str, Any]) -> List[str]:
    tags: List[str] = []

    for item in video_dict.get("textExtra", []) or []:
        hashtag_name = item.get("hashtagName")
        if hashtag_name and hashtag_name not in tags:
            tags.append(hashtag_name)

    for item in video_dict.get("challenges", []) or []:
        title = item.get("title")
        if title and title not in tags:
            tags.append(title)

    return tags


def normalize_video(video_dict: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "video_id": video_dict.get("id"),
        "desc": video_dict.get("desc"),
        "create_time": video_dict.get("createTime"),
        "duration": deep_get(video_dict, "video", "duration"),
        "play_count": deep_get(video_dict, "stats", "playCount"),
        "like_count": deep_get(video_dict, "stats", "diggCount"),
        "comment_count": deep_get(video_dict, "stats", "commentCount"),
        "share_count": deep_get(video_dict, "stats", "shareCount"),
        "author_username": deep_get(video_dict, "author", "uniqueId"),
        "music_title": deep_get(video_dict, "music", "title"),
        "hashtags": extract_hashtags(video_dict),
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_proxy_config(proxy_server: str) -> List[Dict[str, str]]:
    username = os.getenv("PROXY_USERNAME")
    password = os.getenv("PROXY_PASSWORD")

    cfg: Dict[str, str] = {"server": proxy_server}
    if username:
        cfg["username"] = username
    if password:
        cfg["password"] = password
    return [cfg]


def should_rotate_proxy(exc: Exception | str) -> bool:
    text = str(exc).lower()
    keywords = [
        "emptyresponse",
        "timed out",
        "timeout",
        "403",
        "429",
        "captcha",
        "verify",
        "blocked",
        "denied",
        "proxy",
        "connection",
        "session",
        "playwright",
        "browser",
        "challenge",
        "rate limit",
        "no items",
        "failed to fetch",
    ]
    return any(keyword in text for keyword in keywords)


async def collect_once(proxy_server: str, trending_count: int, ms_token: str) -> AttemptResult:
    items: List[Dict[str, Any]] = []
    browser_type = os.getenv("TIKTOK_BROWSER", "webkit")
    sleep_after = int(os.getenv("SESSION_SLEEP_AFTER", "3"))
    start_delay_ms = int(os.getenv("START_DELAY_MS", "0"))

    if start_delay_ms > 0:
        await asyncio.sleep(random.randint(0, start_delay_ms) / 1000)

    try:
        async with TikTokApi() as api:
            await api.create_sessions(
                ms_tokens=[ms_token],
                num_sessions=1,
                sleep_after=sleep_after,
                headless=True,
                browser=browser_type,
                proxies=build_proxy_config(proxy_server),
            )

            async for video in api.trending.videos(count=trending_count):
                raw = getattr(video, "as_dict", None)
                if raw is None and hasattr(video, "as_dict"):
                    raw = video.as_dict
                if callable(raw):
                    raw = raw()
                if not isinstance(raw, dict):
                    raise CollectorError("video payload is not a dict")
                items.append(normalize_video(raw))

        if not items:
            raise CollectorError("no items returned from trending feed")

        return AttemptResult(proxy=proxy_server, ok=True, reason="success", items=items)
    except Exception as exc:  # noqa: BLE001
        return AttemptResult(proxy=proxy_server, ok=False, reason=str(exc), items=[])


async def run() -> None:
    trending_count = int(os.getenv("TRENDING_COUNT", "1"))
    ms_token = os.getenv("MS_TOKEN")
    max_proxies = int(os.getenv("MAX_PROXIES_TO_TRY", "30"))

    if not ms_token:
        raise CollectorError("missing required environment variable: MS_TOKEN")

    proxies = get_proxy_list()
    proxies = proxies[:max_proxies]

    latest_path = Path(os.getenv("LATEST_OUTPUT_PATH", "data/trending_latest.json"))
    history_path = Path(os.getenv("HISTORY_OUTPUT_PATH", "data/trending_history.jsonl"))
    attempt_log_path = Path(os.getenv("ATTEMPT_LOG_PATH", "data/attempt_log.jsonl"))

    collected_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for index, proxy in enumerate(proxies, start=1):
        print(f"[{index}/{len(proxies)}] trying proxy: {proxy}")
        result = await collect_once(proxy, trending_count, ms_token)

        append_jsonl(
            attempt_log_path,
            [
                {
                    "collected_at_utc": collected_at_utc,
                    "proxy": result.proxy,
                    "ok": result.ok,
                    "reason": result.reason,
                }
            ],
        )

        if result.ok:
            payload = {
                "collected_at_utc": collected_at_utc,
                "count": len(result.items),
                "proxy_used": result.proxy,
                "items": result.items,
            }
            write_json(latest_path, payload)
            append_jsonl(
                history_path,
                [
                    {
                        "collected_at_utc": collected_at_utc,
                        "proxy_used": result.proxy,
                        **item,
                    }
                    for item in result.items
                ],
            )
            print(f"success with proxy {result.proxy}; collected {len(result.items)} items")
            return

        print(f"failed with proxy {result.proxy}: {result.reason}")
        if not should_rotate_proxy(result.reason):
            raise CollectorError(f"non-rotatable error: {result.reason}")

    raise CollectorError("all proxies failed")


if __name__ == "__main__":
    asyncio.run(run())
