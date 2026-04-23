#!/usr/bin/env python3
"""
Fetch Bangumi reviews, related blog/log links, and subject comments for a given subject.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from script_logging import get_logger, setup_logging
from script_net import HttpClient, RequestError


BASE = "https://bgm.tv"
API_BASE = "https://api.bgm.tv/v0"
LOGGER = get_logger("fetch_bangumi_logs")
TYPE_PATHS = {"anime": "anime", "manga": "book", "book": "book", "game": "game"}


@dataclass(slots=True)
class Entry:
    kind: str
    source_url: str
    title: str
    author: str
    date: str
    content: str
    url: str
    rating: int | None = None

    @property
    def word_count(self) -> int:
        return len(self.content)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n\n[内容已截断]"
    return text


def build_client(args: argparse.Namespace) -> HttpClient:
    return HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir),
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )


def fetch_subject_info(client: HttpClient, subject_id: str) -> dict:
    try:
        return client.get_json(f"{API_BASE}/subjects/{subject_id}")
    except RequestError as exc:
        LOGGER.warning("subject API 请求失败: %s", exc)
        return {}


def parse_review_detail(html: str, url: str) -> Entry | None:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("#pageHeader h1") or soup.select_one("h1")
    title = normalize_space(title_node.get_text(" ", strip=True)) if title_node else ""
    content_node = soup.select_one(".review_content, #review_content, .message, .entry")
    if not content_node:
        return None
    content = normalize_space(content_node.get_text("\n", strip=True))
    if not content:
        return None

    author_node = soup.select_one(".postTopic .inner strong a, .postTopic a[href*='/user/'], a.avatar")
    date_node = soup.select_one(".tip_j, .small, .time")
    rating = None
    rating_node = soup.select_one(".starlight, .starsinfo, .starstop, .stars, [class*='stars']")
    if rating_node:
        classes = rating_node.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        for cls in classes:
            match = re.search(r"(?:star|starlight|stars)?s(\d{1,3})\b", cls)
            if match:
                value = int(match.group(1))
                rating = value // 10 if value > 10 else value
                break
        if rating is None:
            rating_text = normalize_space(rating_node.get_text(" ", strip=True))
            match = re.search(r"\b(10|[1-9])(?:\s*/\s*10)?\b", rating_text)
            if match:
                rating = int(match.group(1))

    return Entry(
        kind="review",
        source_url="subject reviews",
        title=title,
        author=normalize_space(author_node.get_text(" ", strip=True)) if author_node else "",
        date=normalize_space(date_node.get_text(" ", strip=True)) if date_node else "",
        content=content,
        url=url,
        rating=rating,
    )


def fetch_review_entries(client: HttpClient, subject_id: str, limit: int, max_chars: int, refresh: bool) -> list[Entry]:
    list_url = f"{BASE}/subject/{subject_id}/reviews"
    try:
        html = client.get_text(list_url, force_refresh=refresh)
    except RequestError as exc:
        LOGGER.warning("reviews 页面请求失败: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    entries: list[Entry] = []
    for link in soup.select("a[href*='/review/']"):
        href = link.get("href", "")
        if not href:
            continue
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        try:
            detail_html = client.get_text(url, force_refresh=refresh)
        except RequestError as exc:
            LOGGER.warning("review 详情抓取失败: %s", exc)
            continue
        entry = parse_review_detail(detail_html, url)
        if not entry:
            continue
        entry.content = truncate_text(entry.content, max_chars)
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def parse_blog_detail(html: str, url: str) -> Entry | None:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#viewEntry.entry-container, .entry-container")
    if not container:
        return None
    title_node = container.select_one(".header h1.title, h1.title, h1")
    content_node = container.select_one("#entry_content, .blog_entry, .entry")
    if not content_node:
        return None
    author_node = container.select_one(".author .title a, .userContainer a[href^='/user/']")
    date_node = container.select_one(".header .tools .time, .post_actions .time")
    return Entry(
        kind="blog",
        source_url="subject page blog links",
        title=normalize_space(title_node.get_text(" ", strip=True)) if title_node else "",
        author=normalize_space(author_node.get_text(" ", strip=True)) if author_node else "",
        date=normalize_space(date_node.get_text(" ", strip=True)) if date_node else "",
        content=normalize_space(content_node.get_text("\n", strip=True)),
        url=url,
    )


def fetch_blog_entries(client: HttpClient, subject_id: str, limit: int, max_chars: int, refresh: bool) -> list[Entry]:
    subject_url = f"{BASE}/subject/{subject_id}"
    try:
        html = client.get_text(subject_url, force_refresh=refresh)
    except RequestError as exc:
        LOGGER.warning("subject 页面请求失败: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for node in soup.select("a[href*='/blog/']"):
        href = node.get("href", "")
        if not href:
            continue
        url = urljoin(BASE, href)
        links.append(url)

    entries: list[Entry] = []
    for url in unique_preserve_order(links)[:limit]:
        try:
            detail_html = client.get_text(url, force_refresh=refresh)
        except RequestError as exc:
            LOGGER.warning("blog 详情抓取失败: %s", exc)
            continue
        entry = parse_blog_detail(detail_html, url)
        if not entry or not entry.content:
            continue
        entry.content = truncate_text(entry.content, max_chars)
        entries.append(entry)
    return entries


def fetch_subject_comments(client: HttpClient, subject_id: str, limit: int, max_chars: int, refresh: bool) -> list[Entry]:
    subject_url = f"{BASE}/subject/{subject_id}"
    try:
        html = client.get_text(subject_url, force_refresh=refresh)
    except RequestError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    entries: list[Entry] = []
    seen_contents: set[tuple[str, str, str]] = set()
    for item in soup.select("#comment_box .item, #comment_box .row_reply, .topic_sub_reply"):
        author_node = item.select_one("strong a, a.l, a[href^='/user/']")
        date_node = item.select_one(".tip_j, small, .re_info")
        content_node = item.select_one(".text, .comment, .message, p")
        content = normalize_space(content_node.get_text("\n", strip=True)) if content_node else ""
        if len(content) < 40:
            continue
        author = normalize_space(author_node.get_text(" ", strip=True)) if author_node else ""
        date = normalize_space(date_node.get_text(" ", strip=True)) if date_node else ""
        dedupe_key = (author, date, content)
        if dedupe_key in seen_contents:
            continue
        seen_contents.add(dedupe_key)
        entries.append(
            Entry(
                kind="comment",
                source_url="subject comments",
                title="",
                author=author,
                date=date,
                content=truncate_text(content, max_chars),
                url=subject_url,
            )
        )
        if len(entries) >= limit:
            break
    return entries


def output_markdown(entries: list[Entry], subject_id: str, subject_info: dict, output_path: str | None = None) -> None:
    title = subject_info.get("name_cn") or subject_info.get("name") or f"Subject {subject_id}"
    lines = [f"# Bangumi Logs for {title}", "", f"- subject_id: {subject_id}", f"- fetched_at: {datetime.now(timezone.utc).isoformat()}", ""]
    for index, entry in enumerate(entries, start=1):
        lines.append(f"## {index}. {entry.kind}")
        if entry.title:
            lines.append(f"Title: {entry.title}")
        lines.append(f"Author: {entry.author or '未知'}")
        lines.append(f"Date: {entry.date or '未知'}")
        lines.append(f"URL: {entry.url}")
        if entry.rating is not None:
            lines.append(f"Rating: {entry.rating}/10")
        lines.append("")
        lines.append(entry.content)
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        LOGGER.info("saved markdown to %s", output_path)
        return
    print(text, end="")


def output_json(entries: list[Entry], subject_id: str, subject_info: dict, output_path: str | None = None) -> None:
    payload = {
        "subject_id": subject_id,
        "subject": {
            "name": subject_info.get("name", ""),
            "name_cn": subject_info.get("name_cn", ""),
            "date": subject_info.get("date", ""),
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "entries": [asdict(entry) | {"word_count": entry.word_count} for entry in entries],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        LOGGER.info("saved json to %s", output_path)
        return
    print(text, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch Bangumi reviews/logs for a subject")
    parser.add_argument("--subject-id", required=True, help="Bangumi subject ID")
    parser.add_argument("--subject-type", choices=["anime", "manga", "book", "game"], default="anime", help="Subject type (kept for CLI compatibility)")
    parser.add_argument("--limit", type=int, default=20, help="Max total entries to fetch")
    parser.add_argument("--min-length", type=int, default=100, help="Minimum extracted content length")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--include-comments", action="store_true", help="Also include subject page comments")
    parser.add_argument("--max-chars", type=int, default=6000, help="Max characters per entry")
    parser.add_argument("--cache-dir", default=".cache/bangumi-logs", help="GET response cache directory")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=1.0, help="Minimum interval between requests")
    parser.add_argument("--refresh", action="store_true", help="Bypass disk cache")
    return parser


def main() -> int:
    setup_logging()
    args = build_parser().parse_args()
    client = build_client(args)

    LOGGER.info("fetching Bangumi logs for subject %s", args.subject_id)
    subject_info = fetch_subject_info(client, args.subject_id)
    if not subject_info:
        LOGGER.warning("未获取到 subject API 信息，后续仅依赖网页抓取")

    target_limit = max(1, args.limit)
    entries: list[Entry] = []

    reviews = fetch_review_entries(client, args.subject_id, target_limit, args.max_chars, args.refresh)
    entries.extend(entry for entry in reviews if entry.word_count >= args.min_length)
    LOGGER.info("reviews: %s", len(entries))

    if len(entries) < target_limit:
        missing = target_limit - len(entries)
        blogs = fetch_blog_entries(client, args.subject_id, missing, args.max_chars, args.refresh)
        entries.extend(entry for entry in blogs if entry.word_count >= args.min_length)
        LOGGER.info("reviews + blogs: %s", len(entries))

    if args.include_comments and len(entries) < target_limit:
        missing = target_limit - len(entries)
        comments = fetch_subject_comments(client, args.subject_id, missing, args.max_chars, args.refresh)
        entries.extend(entry for entry in comments if entry.word_count >= args.min_length)
        LOGGER.info("reviews + blogs + comments: %s", len(entries))

    if not entries:
        LOGGER.error("未抓到可用长评/日志。Bangumi 该条目可能没有公开 reviews，subject 页也未暴露可解析 blog 入口。")
        return 3

    deduped_entries: list[Entry] = []
    seen_entry_keys: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        key = (entry.kind, entry.url, entry.author, entry.content)
        if key in seen_entry_keys:
            continue
        seen_entry_keys.add(key)
        deduped_entries.append(entry)

    entries = deduped_entries[:target_limit]
    if args.json or (args.output and args.output.endswith(".json")):
        output_json(entries, args.subject_id, subject_info, args.output)
    else:
        output_markdown(entries, args.subject_id, subject_info, args.output)

    LOGGER.info("done: %s entries", len(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
