#!/usr/bin/env python3
"""
Collect normalized book-writing materials from EPUB files, web URLs, and Bangumi subject inputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ebooklib import epub

from fetch_web_content import fetch_url
from read_epub import clean_html_to_text, extract_chapters, extract_metadata, parse_chapter_selection
from resolve_subject import extract_subject_id_from_url, fetch_subject_detail, resolve_subject
from script_http import HttpClient, RequestError, get_logger, setup_logging


LOGGER = get_logger("collect_book_materials")
BOOK_DOMAIN = "book"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect normalized materials for Bangumi-style book writing"
    )
    parser.add_argument("--epub", action="append", default=[], help="EPUB file path(s) to extract")
    parser.add_argument("--url", action="append", default=[], help="Book-related URL(s) to fetch")
    parser.add_argument("--subject-id", type=int, help="Bangumi subject ID")
    parser.add_argument("--subject-url", type=str, help="Bangumi subject URL")
    parser.add_argument("--title", "--query", dest="title", help="Bangumi book title to search")
    parser.add_argument("--input", type=str, help="Auto-detect Bangumi URL or title")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Output format")
    parser.add_argument("--chapters", type=str, help="EPUB chapter range, e.g. '1-5' or 'all'")
    parser.add_argument(
        "--epub-max-chars",
        type=int,
        default=50000,
        help="Max characters per EPUB chapter (0 for unlimited)",
    )
    parser.add_argument("--metadata-only", action="store_true", help="Only extract EPUB metadata")
    parser.add_argument(
        "--extract-body",
        dest="extract_body",
        action="store_true",
        help="Extract readable text from web pages (default behavior)",
    )
    parser.add_argument(
        "--no-extract-body",
        "--raw-html",
        dest="extract_body",
        action="store_false",
        help="Keep raw HTML for fetched web pages",
    )
    parser.add_argument("--web-max-chars", type=int, default=50000, help="Max characters per fetched web page")
    parser.add_argument(
        "--cache-dir",
        default=".cache/book-materials",
        help="Base cache directory for subject resolution and web fetching",
    )
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.6, help="Minimum interval between requests")
    parser.set_defaults(extract_body=None)
    return parser


def classify_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    bangumi_subject_urls: list[str] = []
    web_urls: list[str] = []
    for url in urls:
        if extract_subject_id_from_url(url):
            bangumi_subject_urls.append(url)
        else:
            web_urls.append(url)
    return bangumi_subject_urls, web_urls


def build_subject_selector(
    args: argparse.Namespace,
    bangumi_subject_urls: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    explicit: list[tuple[str, Any]] = []
    if args.subject_id is not None:
        explicit.append(("subject_id", args.subject_id))
    if args.subject_url:
        explicit.append(("subject_url", args.subject_url))
    if args.title:
        explicit.append(("query", args.title))
    if args.input:
        explicit.append(("input_value", args.input))

    if len(explicit) > 1:
        fields = ", ".join(name for name, _ in explicit)
        raise ValueError(f"only one Bangumi selector may be provided at a time: {fields}")

    detected_ids = {extract_subject_id_from_url(url) for url in bangumi_subject_urls if extract_subject_id_from_url(url)}
    if len(detected_ids) > 1 and not explicit:
        raise ValueError("multiple Bangumi subject URLs were provided via --url; please keep one or use --subject-id")

    if bangumi_subject_urls:
        warnings.append("Bangumi subject URL(s) passed via --url were used for subject resolution and skipped from generic web fetching.")

    if explicit:
        key, value = explicit[0]
        return {key: value}, warnings

    if bangumi_subject_urls:
        return {"subject_url": bangumi_subject_urls[0]}, warnings

    return None, warnings


def flatten_infobox_value(value: object) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for entry in value:
            if isinstance(entry, dict):
                text = str(entry.get("v", "")).strip()
                if text:
                    parts.append(text)
            elif entry:
                parts.append(str(entry).strip())
        return ", ".join(part for part in parts if part)
    return str(value).strip()


def normalize_book_subject(detail: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    infobox: dict[str, str] = {}
    for item in detail.get("infobox", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        value = flatten_infobox_value(item.get("value", ""))
        if value:
            infobox[key] = value

    tags = []
    for item in detail.get("tags", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name and name not in tags:
            tags.append(name)

    best_match = resolution.get("best_match") or {}
    subject_id = detail.get("id") or resolution.get("subject_id")
    return {
        "subject_id": subject_id,
        "title": detail.get("name", "") or best_match.get("name", ""),
        "title_cn": detail.get("name_cn", "") or best_match.get("name_cn", ""),
        "date": detail.get("date", "") or best_match.get("date", ""),
        "platform": detail.get("platform", "") or best_match.get("platform", ""),
        "url": best_match.get("url", "") or (f"https://bgm.tv/subject/{subject_id}" if subject_id else ""),
        "summary": detail.get("summary", "") or "",
        "volumes": detail.get("volumes"),
        "total_episodes": detail.get("eps"),
        "tags": tags,
        "infobox": infobox,
    }


def collect_subject_material(
    client: HttpClient,
    selector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, int]:
    resolution, exit_code = resolve_subject(client, domain=BOOK_DOMAIN, **selector)
    subject_id = resolution.get("subject_id")
    if exit_code not in (0, 5) or not subject_id:
        return resolution, None, exit_code

    try:
        detail = fetch_subject_detail(client, int(subject_id))
    except RequestError as exc:
        LOGGER.warning("failed to fetch full Bangumi subject detail: %s", exc)
        detail = {}

    subject = normalize_book_subject(detail, resolution)
    material = {
        "kind": "bangumi_subject",
        "source": subject.get("url", ""),
        "title": subject.get("title_cn") or subject.get("title") or "",
        "content": subject.get("summary", ""),
        "metadata": {
            "subject_id": subject.get("subject_id"),
            "title": subject.get("title", ""),
            "title_cn": subject.get("title_cn", ""),
            "date": subject.get("date", ""),
            "platform": subject.get("platform", ""),
            "url": subject.get("url", ""),
            "volumes": subject.get("volumes"),
            "total_episodes": subject.get("total_episodes"),
            "tags": subject.get("tags", []),
            "infobox": subject.get("infobox", {}),
            "resolved_via": resolution.get("match_type"),
            "query": resolution.get("query"),
        },
    }
    return resolution, {"subject": subject, "material": material}, exit_code


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n\n[... truncated ...]", True
    return text, False


def collect_epub_material(
    path: str,
    *,
    chapter_range: str | None,
    max_chars: int,
    metadata_only: bool,
) -> dict[str, Any]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"EPUB file not found: {input_path}")

    book = epub.read_epub(str(input_path))
    metadata = extract_metadata(book)
    result: dict[str, Any] = {
        "kind": "epub",
        "source": str(input_path),
        "title": metadata.get("title") or input_path.stem,
        "content": "",
        "metadata": metadata,
        "chapter_count": 0,
        "selected_chapter_count": 0,
        "chapters": [],
    }

    chapters = extract_chapters(book)
    result["chapter_count"] = len(chapters)
    if metadata_only:
        return result

    start, end = parse_chapter_selection(chapter_range, len(chapters))
    selected = chapters[start:end]
    if not selected:
        raise ValueError(f"selected chapter range is empty for {input_path}")

    rendered_sections: list[str] = []
    for index, chapter in enumerate(selected, start=start + 1):
        chapter_title = chapter["title"] or f"Chapter {index}"
        text, truncated = truncate_text(clean_html_to_text(chapter["content"]), max_chars)
        chapter_payload = {
            "index": index,
            "id": chapter["id"],
            "file_name": chapter["file_name"],
            "title": chapter_title,
            "content": text,
            "truncated": truncated,
        }
        result["chapters"].append(chapter_payload)
        rendered_sections.append(f"## {chapter_title}\n\n{text or '[空章节]'}")

    result["selected_chapter_count"] = len(selected)
    result["content"] = "\n\n---\n\n".join(rendered_sections)
    return result


def collect_web_materials(
    client: HttpClient,
    urls: list[str],
    *,
    extract_body_mode: bool,
    max_chars: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    materials: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in urls:
        result = fetch_url(client, url, extract_main=extract_body_mode, max_chars=max_chars)
        if not result.get("success"):
            message = str(result.get("error", "unknown error"))
            errors.append(f"{url}: {message}")
            continue
        materials.append(
            {
                "kind": "web_page",
                "source": url,
                "title": str(result.get("title", "") or ""),
                "content": str(result.get("content", "") or ""),
                "metadata": {
                    "fetched_at": result.get("fetched_at"),
                    "mode": result.get("mode"),
                    "truncated": bool(result.get("truncated")),
                },
            }
        )
    return materials, errors


def collect_book_bundle(args: argparse.Namespace, client: HttpClient | None = None) -> tuple[dict[str, Any], int]:
    if not any([args.epub, args.url, args.subject_id is not None, args.subject_url, args.title, args.input]):
        raise ValueError("provide at least one of --epub, --url, --subject-id, --subject-url, --title/--query, or --input")

    bangumi_subject_urls, web_urls = classify_urls(list(args.url))
    subject_selector, warnings = build_subject_selector(args, bangumi_subject_urls)
    extract_body_mode = True if args.extract_body is None else args.extract_body

    bundle = {
        "bundle_type": "book_materials",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "epub_files": list(args.epub),
            "urls": list(args.url),
            "subject_selector": subject_selector or {},
            "chapter_range": args.chapters or "all",
            "metadata_only": bool(args.metadata_only),
            "web_mode": "extract" if extract_body_mode else "raw-html",
        },
        "subject_resolution": None,
        "subject": None,
        "materials": [],
        "warnings": warnings,
        "errors": [],
    }

    client = client or HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir) / "http",
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )

    success_count = 0
    had_issues = False
    requested_count = len(args.epub) + len(web_urls) + (1 if subject_selector else 0)

    if subject_selector:
        try:
            resolution, subject_payload, resolution_exit_code = collect_subject_material(client, subject_selector)
        except Exception as exc:  # noqa: BLE001
            bundle["errors"].append(f"Bangumi subject: {exc}")
            had_issues = True
        else:
            bundle["subject_resolution"] = resolution
            if subject_payload is not None:
                bundle["subject"] = subject_payload["subject"]
                bundle["materials"].append(subject_payload["material"])
                success_count += 1
            if resolution_exit_code != 0:
                error = resolution.get("error") or {}
                message = error.get("message") or "Bangumi subject resolution needs confirmation"
                bundle["warnings"].append(f"Bangumi subject: {message}")
                had_issues = True
            elif subject_payload is None:
                error = resolution.get("error") or {}
                message = error.get("message") or "Bangumi subject resolution failed"
                bundle["errors"].append(f"Bangumi subject: {message}")
                had_issues = True

    for path in args.epub:
        try:
            material = collect_epub_material(
                path,
                chapter_range=args.chapters,
                max_chars=args.epub_max_chars,
                metadata_only=args.metadata_only,
            )
        except Exception as exc:  # noqa: BLE001
            bundle["errors"].append(f"{path}: {exc}")
            had_issues = True
            continue
        bundle["materials"].append(material)
        success_count += 1

    web_materials, web_errors = collect_web_materials(
        client,
        web_urls,
        extract_body_mode=extract_body_mode,
        max_chars=args.web_max_chars,
    )
    bundle["materials"].extend(web_materials)
    bundle["errors"].extend(web_errors)
    if web_errors:
        had_issues = True
    success_count += len(web_materials)

    if requested_count == 0:
        requested_count = len(args.url)

    if success_count == requested_count and not had_issues:
        exit_code = 0
    elif success_count > 0:
        exit_code = 1
    else:
        exit_code = 2

    return bundle, exit_code


def render_markdown(bundle: dict[str, Any]) -> str:
    lines = ["# Book Materials Bundle", ""]
    lines.append(f"- Generated At: {bundle.get('generated_at', '')}")
    lines.append(f"- Material Count: {len(bundle.get('materials', []))}")
    lines.append("")

    subject = bundle.get("subject")
    if subject:
        lines.append("## Bangumi Subject")
        lines.append("")
        lines.append(f"- Subject ID: {subject.get('subject_id') or ''}")
        lines.append(f"- Title: {subject.get('title_cn') or subject.get('title') or ''}")
        if subject.get("title_cn") and subject.get("title"):
            lines.append(f"- Original Title: {subject.get('title')}")
        if subject.get("date"):
            lines.append(f"- Date: {subject.get('date')}")
        if subject.get("url"):
            lines.append(f"- URL: {subject.get('url')}")
        tags = subject.get("tags") or []
        if tags:
            lines.append(f"- Tags: {', '.join(tags)}")
        if subject.get("summary"):
            lines.extend(["", "### Summary", "", subject["summary"], ""])

    for material in bundle.get("materials", []):
        kind = material.get("kind")
        if kind == "bangumi_subject":
            continue
        if kind == "epub":
            lines.append(f"## EPUB: {material.get('source', '')}")
            lines.append("")
            metadata = material.get("metadata", {})
            for key in ("title", "author", "language", "publisher", "date", "identifier", "description"):
                value = metadata.get(key)
                if value:
                    lines.append(f"- {key.title()}: {value}")
            lines.append(f"- Selected Chapters: {material.get('selected_chapter_count', 0)} / {material.get('chapter_count', 0)}")
            lines.append("")
            content = str(material.get("content", "") or "").strip()
            if content:
                lines.append(content)
                lines.append("")
        elif kind == "web_page":
            lines.append(f"## Web: {material.get('source', '')}")
            lines.append("")
            if material.get("title"):
                lines.append(f"- Title: {material.get('title')}")
            metadata = material.get("metadata", {})
            if metadata.get("fetched_at"):
                lines.append(f"- Fetched At: {metadata.get('fetched_at')}")
            if metadata.get("mode"):
                lines.append(f"- Mode: {metadata.get('mode')}")
            lines.append("")
            lines.append(str(material.get("content", "")))
            lines.append("")

    warnings = bundle.get("warnings") or []
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    errors = bundle.get("errors") or []
    if errors:
        lines.append("## Errors")
        lines.append("")
        for error in errors:
            lines.append(f"- {error}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def emit_output(bundle: dict[str, Any], *, output: str | None, output_format: str) -> None:
    if output_format == "markdown":
        text = render_markdown(bundle)
    else:
        text = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"

    if output:
        Path(output).write_text(text, encoding="utf-8")
        LOGGER.info("output written to %s", output)
        return
    sys.stdout.write(text)


def infer_output_format(args: argparse.Namespace) -> str:
    if args.output and args.output.lower().endswith((".md", ".markdown")):
        return "markdown"
    if args.output and args.output.lower().endswith(".json"):
        return "json"
    return args.format


def main() -> int:
    setup_logging()
    args = build_parser().parse_args()
    try:
        bundle, exit_code = collect_book_bundle(args)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2

    emit_output(bundle, output=args.output, output_format=infer_output_format(args))

    LOGGER.info(
        "collected %s material(s) with %s warning(s) and %s error(s)",
        len(bundle["materials"]),
        len(bundle["warnings"]),
        len(bundle["errors"]),
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
