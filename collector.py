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


def should_rotate_proxy(reason: Exception | str) -> bool:
    text = str(reason).lower()

    # 这些属于程序自身或配置问题，不应继续无意义换代理
    non_rotatable_keywords = [
        "missing required environment variable",
        "video payload is not a dict",
        "proxy file downloaded successfully but no valid proxies were found",
        "failed to download proxy file after",
        "invalid literal for int()",
    ]

    if any(keyword in text for keyword in non_rotatable_keywords):
        return False

    # 其它情况默认都当成代理/网络/风控问题，继续切代理
    return True


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

    proxy_server = proxy_server.strip()
    proxy_lower = proxy_server.lower()

    if proxy_lower.startswith("socks5h://"):
        proxy_server = "socks5://" + proxy_server[len("socks5h://"):]

    elif not proxy_lower.startswith(("http://", "https://", "socks5://")):
        proxy_server = f"socks5://{proxy_server}"

    cfg: Dict[str, str] = {"server": proxy_server}
    if username:
        cfg["username"] = username
    if password:
        cfg["password"] = password
    return [cfg]


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
                if callable(raw):
                    raw = raw()

                if not isinstance(raw, dict):
                    raise CollectorError("video payload is not a dict")

                items.append(normalize_video(raw))

        if not items:
            raise CollectorError("no items returned from trending feed")

        return AttemptResult(proxy=proxy_server, ok=True, reason="success", items=items)

    except Exception as exc:
        return AttemptResult(proxy=proxy_server, ok=False, reason=str(exc), items=[])


async def run() -> None:
    trending_count = int(os.getenv("TRENDING_COUNT", "1"))
    ms_token = os.getenv("MS_TOKEN")
    max_proxies_raw = os.getenv("MAX_PROXIES_TO_TRY", "").strip()

    if not ms_token:
        raise CollectorError("missing required environment variable: MS_TOKEN")

    proxies = get_proxy_list()

    # 优先尝试 socks5，再尝试 http/https
    proxies = sorted(
        proxies,
        key=lambda p: (
            0 if p.lower().startswith("socks5://") else 1,
            p,
        ),
    )

    if max_proxies_raw:
        max_proxies = int(max_proxies_raw)
        proxies = proxies[:max_proxies]
        print(f"limiting proxies to first {len(proxies)} entries")
    else:
        print(f"using all proxies from remote file: {len(proxies)} entries")

    if not proxies:
        raise CollectorError("no proxies loaded")

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
                "status": "success",
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

        if should_rotate_proxy(result.reason):
            print("rotating to next proxy...")
            continue

        raise CollectorError(f"non-rotatable error: {result.reason}")

    failure_payload = {
        "collected_at_utc": collected_at_utc,
        "count": 0,
        "proxy_used": None,
        "items": [],
        "status": "all_proxies_failed",
    }
    write_json(latest_path, failure_payload)
    print("all proxies failed")
    return


if __name__ == "__main__":
    asyncio.run(run())
