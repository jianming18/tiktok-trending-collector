from __future__ import annotations

import asyncio
import json
import os
import random
import re
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

    non_rotatable_keywords = [
        "missing required environment variable",
        "video payload is not a dict",
        "proxy file downloaded successfully but no valid proxies were found",
        "failed to download proxy file after",
        "invalid literal for int()",
    ]

    if any(keyword in text for keyword in non_rotatable_keywords):
        return False

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


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_rate(numerator: Any, denominator: Any) -> float:
    num = to_float(numerator, 0.0)
    den = to_float(denominator, 0.0)
    if den <= 0:
        return 0.0
    return round(num / den, 6)


def has_emoji(text: str) -> bool:
    if not text:
        return False
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002700-\U000027BF"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    return bool(emoji_pattern.search(text))


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


def build_video_url(author_username: str, video_id: str) -> str:
    if not author_username or not video_id:
        return ""
    return f"https://www.tiktok.com/@{author_username}/video/{video_id}"


def normalize_video(video_dict: Dict[str, Any]) -> Dict[str, Any]:
    desc = video_dict.get("desc") or ""
    create_time = to_int(video_dict.get("createTime"), 0)

    play_count = to_int(deep_get(video_dict, "stats", "playCount"), 0)
    like_count = to_int(deep_get(video_dict, "stats", "diggCount"), 0)
    comment_count = to_int(deep_get(video_dict, "stats", "commentCount"), 0)
    share_count = to_int(deep_get(video_dict, "stats", "shareCount"), 0)
    favorite_count = to_int(
        deep_get(video_dict, "stats", "collectCount", default=None)
        if deep_get(video_dict, "stats", "collectCount", default=None) is not None
        else deep_get(video_dict, "stats", "favoriteCount"),
        0,
    )

    author_id = str(deep_get(video_dict, "author", "id") or "")
    author_username = str(deep_get(video_dict, "author", "uniqueId") or "")
    author_nickname = str(deep_get(video_dict, "author", "nickname") or "")
    author_verified = bool(deep_get(video_dict, "author", "verified", default=False))
    author_follower_count = to_int(
        deep_get(video_dict, "authorStats", "followerCount", default=None)
        if deep_get(video_dict, "authorStats", "followerCount", default=None) is not None
        else deep_get(video_dict, "author", "followerCount"),
        0,
    )
    author_video_count = to_int(
        deep_get(video_dict, "authorStats", "videoCount", default=None)
        if deep_get(video_dict, "authorStats", "videoCount", default=None) is not None
        else deep_get(video_dict, "author", "videoCount"),
        0,
    )
    author_total_likes = to_int(
        deep_get(video_dict, "authorStats", "heartCount", default=None)
        if deep_get(video_dict, "authorStats", "heartCount", default=None) is not None
        else deep_get(video_dict, "author", "heartCount"),
        0,
    )

    music_id = str(deep_get(video_dict, "music", "id") or "")
    music_title = str(deep_get(video_dict, "music", "title") or "")

    hashtags = extract_hashtags(video_dict)
    hashtag_count = len(hashtags)

    region = (
        video_dict.get("region")
        or video_dict.get("regionCode")
        or deep_get(video_dict, "locationCreated")
        or ""
    )

    duration = to_int(deep_get(video_dict, "video", "duration"), 0)
    video_id = str(video_dict.get("id") or "")
    video_url = build_video_url(author_username, video_id)

    is_ad = bool(
        video_dict.get("isAd", False)
        or video_dict.get("isSponsored", False)
        or deep_get(video_dict, "commerceInfo", "advPromotable", default=False)
    )

    engagement_total = like_count + comment_count + share_count + favorite_count

    posted_hour_utc = 0
    posted_weekday_utc = 0
    if create_time > 0:
        dt = datetime.fromtimestamp(create_time, tz=timezone.utc)
        posted_hour_utc = dt.hour
        posted_weekday_utc = dt.weekday()

    return {
        # 23 original fields
        "video_id": video_id,
        "video_url": video_url,
        "desc": desc,
        "create_time": create_time,
        "duration": duration,
        "region": region,
        "play_count": play_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "share_count": share_count,
        "favorite_count": favorite_count,
        "author_id": author_id,
        "author_username": author_username,
        "author_nickname": author_nickname,
        "author_verified": author_verified,
        "author_follower_count": author_follower_count,
        "author_video_count": author_video_count,
        "author_total_likes": author_total_likes,
        "music_id": music_id,
        "music_title": music_title,
        "hashtags": hashtags,
        "hashtag_count": hashtag_count,
        "is_ad": is_ad,
        # 9 derived fields
        "engagement_total": engagement_total,
        "like_rate": safe_rate(like_count, play_count),
        "comment_rate": safe_rate(comment_count, play_count),
        "share_rate": safe_rate(share_count, play_count),
        "favorite_rate": safe_rate(favorite_count, play_count),
        "posted_hour_utc": posted_hour_utc,
        "posted_weekday_utc": posted_weekday_utc,
        "desc_length": len(desc),
        "has_emoji": has_emoji(desc),
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
