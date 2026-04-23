#!/usr/bin/env python3
"""
Fetch web content from user-provided URLs.
Supports static HTML extraction with optional raw HTML output.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from script_http import HttpClient, RequestError, get_logger, setup_logging


LOGGER = get_logger("fetch_web_content")


def extract_body(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()

    title_node = soup.find("title")
    title = title_node.get_text(" ", strip=True) if title_node else ""

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find("div", class_="content")
        or soup.find("body")
    )
    if not main:
        return {"title": title, "content": ""}

    text = main.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return {"title": title, "content": "\n\n".join(lines)}


def fetch_url(client: HttpClient, url: str, *, extract_main: bool, max_chars: int) -> dict[str, object]:
    try:
        html = client.get_text(url)
        result = extract_body(html) if extract_main else {"title": "", "content": html}
        content = result["content"]
        truncated = False
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n\n[内容已截断]"
            truncated = True
        return {
            "success": True,
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "title": result["title"],
            "content": content,
            "truncated": truncated,
            "mode": "extract" if extract_main else "raw-html",
        }
    except RequestError as exc:
        return {
            "success": False,
            "url": url,
            "error": str(exc),
            "status_code": exc.status_code,
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "url": url, "error": str(exc)}


def output_markdown(results: list[dict[str, object]], output_path: str | None = None) -> None:
    lines = ["# Web Content", ""]
    for result in results:
        if not result["success"]:
            lines.append(f"## Failed: {result['url']}")
            lines.append(f"Error: {result['error']}")
            lines.append("")
            continue
        lines.append(f"## Source: {result['url']}")
        lines.append(f"Fetched: {result['fetched_at']}")
        if result.get("title"):
            lines.append(f"Title: {result['title']}")
        lines.append("")
        lines.append(str(result["content"]))
        lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
        LOGGER.info("saved markdown to %s", output_path)
        return
    print(content)


def output_json(results: list[dict[str, object]], output_path: str | None = None) -> None:
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        LOGGER.info("saved json to %s", output_path)
        return
    print(text, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch web content for Bangumi comment writing")
    parser.add_argument("--url", action="append", required=True, help="URL(s) to fetch")
    parser.add_argument("--output", "-o", help="Output file path")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--extract-body",
        dest="extract_body",
        action="store_true",
        help="Extract readable body text (default behavior)",
    )
    mode_group.add_argument(
        "--no-extract-body",
        "--raw-html",
        dest="extract_body",
        action="store_false",
        help="Keep raw HTML instead of extracting body text",
    )
    parser.add_argument("--max-chars", type=int, default=50000, help="Max characters per page (0 for unlimited)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of Markdown")
    parser.add_argument("--cache-dir", default=".cache/web-content", help="GET response cache directory")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.5, help="Minimum interval between requests")
    parser.set_defaults(extract_body=None)
    return parser


def main() -> int:
    setup_logging()
    args = build_parser().parse_args()
    extract_body_mode = True if args.extract_body is None else args.extract_body

    client = HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir),
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )

    LOGGER.info("fetching %s page(s) in %s mode", len(args.url), "extract" if extract_body_mode else "raw-html")
    results: list[dict[str, object]] = []
    for index, url in enumerate(args.url, start=1):
        LOGGER.info("(%s/%s) %s", index, len(args.url), url)
        result = fetch_url(client, url, extract_main=extract_body_mode, max_chars=args.max_chars)
        results.append(result)
        if result["success"]:
            LOGGER.info("fetched %s chars", len(str(result["content"])))
        else:
            LOGGER.error("failed: %s", result["error"])

    if args.json or (args.output and args.output.endswith(".json")):
        output_json(results, args.output)
    else:
        output_markdown(results, args.output)

    success_count = sum(1 for item in results if item["success"])
    LOGGER.info("completed: %s/%s succeeded", success_count, len(results))
    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
