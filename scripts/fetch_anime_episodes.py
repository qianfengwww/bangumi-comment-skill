#!/usr/bin/env python3
"""
Fetch anime episode summaries from Bangumi API and web pages.

Usage:
    python fetch_anime_episodes.py --subject-id 12345
    python fetch_anime_episodes.py --subject-id 12345 --output episodes.json

Output:
    List of episodes with id, sort order, name, name_cn, desc (summary), air_date
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from script_http import HttpClient, RequestError, get_logger, setup_logging

BANGUMI_API_BASE = "https://api.bgm.tv/v0"
LOGGER = get_logger("fetch_anime_episodes")


def fetch_episodes_from_api(client: HttpClient, subject_id: int, limit: int = 100) -> list[dict]:
    """Fetch episode list from Bangumi API."""
    url = f"{BANGUMI_API_BASE}/episodes"
    params = {"subject_id": subject_id, "limit": limit}
    try:
        data = client.get_json(url, params=params)
        return data.get("data", [])
    except RequestError as exc:
        LOGGER.warning("API 请求失败: %s", exc)
        return []


def fetch_episode_detail_from_web(client: HttpClient, episode_id: int) -> str | None:
    """Fetch detailed episode summary from Bangumi web page."""
    url = f"https://bgm.tv/ep/{episode_id}"
    try:
        soup = BeautifulSoup(client.get_text(url), "html.parser")

        # Look for episode summary in the page
        # Bangumi episode pages have summary in <div class="topic"> or similar
        summary_div = soup.find("div", class_="topic")
        if summary_div:
            # Extract text, remove extra whitespace
            text = summary_div.get_text(strip=True)
            # Clean up: remove "剧情简介" labels etc.
            text = re.sub(r"\s+", " ", text)
            if len(text) > 50:  # Only return if substantial
                return text
        
        # Alternative: look for desc in episode detail section
        desc_section = soup.find("div", id="episode_desc")
        if desc_section:
            text = desc_section.get_text(strip=True)
            text = re.sub(r"\s+", " ", text)
            if len(text) > 50:
                return text
        
    except RequestError as exc:
        LOGGER.warning("网页抓取失败，ep=%s: %s", episode_id, exc)
        return None


def fetch_subject_summary(client: HttpClient, subject_id: int) -> str | None:
    """Fetch overall subject summary from Bangumi API."""
    url = f"{BANGUMI_API_BASE}/subjects/{subject_id}"
    try:
        data = client.get_json(url)
        summary = data.get("summary", "")
        if summary and len(summary) > 50:
            return summary
        return None
    except RequestError as exc:
        LOGGER.warning("条目简介抓取失败: %s", exc)
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch anime episode summaries from Bangumi")
    parser.add_argument("--subject-id", type=int, required=True, help="Bangumi subject ID")
    parser.add_argument("--limit", type=int, default=100, help="Max episodes to fetch")
    parser.add_argument("--fetch-web-detail", action="store_true", help="Fetch detailed summaries from web pages (slower)")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--cache-dir", default=".cache/anime-episodes", help="GET response cache directory")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.8, help="Minimum interval between requests")
    return parser


def main() -> int:
    setup_logging()
    args = build_parser().parse_args()

    client = HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir),
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )

    LOGGER.info("fetching episodes for subject %s", args.subject_id)

    # Step 1: Get episode list from API
    episodes = fetch_episodes_from_api(client, args.subject_id, args.limit)
    if not episodes:
        LOGGER.error("no episodes found or API request failed")
        return 1

    LOGGER.info("found %s episodes from API", len(episodes))

    # Step 2: Enrich with web details if requested
    if args.fetch_web_detail:
        LOGGER.info("fetching detailed summaries from web pages")
        for i, ep in enumerate(episodes):
            ep_id = ep.get("id")
            if ep_id:
                web_desc = fetch_episode_detail_from_web(client, ep_id)
                if web_desc:
                    # Prefer web detail over API desc
                    ep["desc"] = web_desc
                    ep["desc_source"] = "web"
                else:
                    ep["desc_source"] = "api"
            if (i + 1) % 10 == 0:
                LOGGER.info("progress: %s/%s episodes", i + 1, len(episodes))
    else:
        for ep in episodes:
            ep["desc_source"] = "api"

    # Step 3: Fetch subject-level summary
    subject_summary = fetch_subject_summary(client, args.subject_id)

    # Step 4: Build output
    result = {
        "subject_id": args.subject_id,
        "subject_summary": subject_summary,
        "episodes": [
            {
                "id": ep.get("id"),
                "sort": ep.get("sort"),
                "name": ep.get("name", ""),
                "name_cn": ep.get("name_cn", ""),
                "desc": ep.get("desc", ""),
                "desc_source": ep.get("desc_source", "api"),
                "air_date": ep.get("air_date", ""),
                "duration": ep.get("duration", ""),
            }
            for ep in episodes
        ],
    }
    
    # Step 5: Output
    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output_json, encoding="utf-8")
        LOGGER.info("output written to %s", output_path)
    else:
        print(output_json)

    LOGGER.info("done. %s episodes fetched", len(episodes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
