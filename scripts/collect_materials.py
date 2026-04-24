#!/usr/bin/env python3
"""
Collect normalized writing materials for Bangumi anime, book, and game domains.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from resolve_subject import extract_subject_id_from_url
from script_http import HttpClient, get_logger, setup_logging


LOGGER = get_logger("collect_materials")
SUPPORTED_DOMAINS = ("anime", "book", "game")


def _resolve_subject(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], int]:
    from resolve_subject import resolve_subject

    return resolve_subject(*args, **kwargs)


def _fetch_anime_episodes_from_api(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from fetch_anime_episodes import fetch_episodes_from_api

    return fetch_episodes_from_api(*args, **kwargs)


def _fetch_anime_episode_detail(*args: Any, **kwargs: Any) -> str | None:
    from fetch_anime_episodes import fetch_episode_detail_from_web

    return fetch_episode_detail_from_web(*args, **kwargs)


def _fetch_anime_subject_summary(*args: Any, **kwargs: Any) -> str | None:
    from fetch_anime_episodes import fetch_subject_summary

    return fetch_subject_summary(*args, **kwargs)


def _fetch_game_subject_api(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    from fetch_game_plot import fetch_subject_from_api

    return fetch_subject_from_api(*args, **kwargs)


def _fetch_game_subject_web(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from fetch_game_plot import fetch_subject_from_web

    return fetch_subject_from_web(*args, **kwargs)


def _extract_game_plot_elements(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from fetch_game_plot import extract_plot_elements

    return extract_plot_elements(*args, **kwargs)


def _generate_game_guidance(*args: Any, **kwargs: Any) -> str:
    from fetch_game_plot import generate_plot_guidance

    return generate_plot_guidance(*args, **kwargs)


def _fetch_url(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from fetch_web_content import fetch_url

    return fetch_url(*args, **kwargs)


def _fetch_subject_info(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from fetch_bangumi_logs import fetch_subject_info

    return fetch_subject_info(*args, **kwargs)


def _fetch_review_entries(*args: Any, **kwargs: Any) -> list[Any]:
    from fetch_bangumi_logs import fetch_review_entries

    return fetch_review_entries(*args, **kwargs)


def _fetch_blog_entries(*args: Any, **kwargs: Any) -> list[Any]:
    from fetch_bangumi_logs import fetch_blog_entries

    return fetch_blog_entries(*args, **kwargs)


def _fetch_subject_comments(*args: Any, **kwargs: Any) -> list[Any]:
    from fetch_bangumi_logs import fetch_subject_comments

    return fetch_subject_comments(*args, **kwargs)


def _collect_book_bundle(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], int]:
    from collect_book_materials import collect_book_bundle

    return collect_book_bundle(*args, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect normalized Bangumi writing materials for anime, book, or game"
    )
    parser.add_argument("--domain", choices=SUPPORTED_DOMAINS, required=True, help="Target domain")
    parser.add_argument("--subject-id", type=int, help="Bangumi subject ID")
    parser.add_argument("--subject-url", type=str, help="Bangumi subject URL")
    parser.add_argument("--title", "--query", dest="title", help="Title query for Bangumi subject search")
    parser.add_argument("--input", type=str, help="Auto-detect Bangumi URL or title query")
    parser.add_argument("--url", action="append", default=[], help="Generic URL(s) or Bangumi subject URL")
    parser.add_argument("--epub", action="append", default=[], help="EPUB file path(s), book only")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Output format")
    parser.add_argument("--include-bangumi-logs", action="store_true", help="Fetch Bangumi reviews/blogs/comments")
    parser.add_argument("--include-comments", action="store_true", help="Include subject comments in Bangumi logs")
    parser.add_argument("--log-limit", type=int, default=8, help="Max Bangumi log entries to keep")
    parser.add_argument("--log-min-length", type=int, default=150, help="Minimum Bangumi log length")
    parser.add_argument("--fetch-web-detail", action="store_true", help="Anime only: fetch episode detail pages")
    parser.add_argument("--include-guidance", action="store_true", help="Game only: include guidance text")
    parser.add_argument("--chapters", type=str, help="Book only: EPUB chapter range, e.g. 1-5 or all")
    parser.add_argument("--metadata-only", action="store_true", help="Book only: extract EPUB metadata only")
    parser.add_argument("--epub-max-chars", type=int, default=50000, help="Book only: max chars per EPUB chapter")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--extract-body",
        dest="extract_body",
        action="store_true",
        help="Extract readable body text from generic URLs (default)",
    )
    mode_group.add_argument(
        "--no-extract-body",
        "--raw-html",
        dest="extract_body",
        action="store_false",
        help="Keep raw HTML for generic URLs",
    )
    parser.add_argument("--web-max-chars", type=int, default=50000, help="Max characters per generic URL")
    parser.add_argument("--cache-dir", default=".cache/materials", help="Base cache directory")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.8, help="Minimum interval between requests")
    parser.set_defaults(extract_body=None)
    return parser


def classify_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    bangumi_subject_urls: list[str] = []
    generic_urls: list[str] = []
    for url in urls:
        if extract_subject_id_from_url(url):
            bangumi_subject_urls.append(url)
        else:
            generic_urls.append(url)
    return bangumi_subject_urls, generic_urls


def build_subject_selector(
    *,
    subject_id: int | None,
    subject_url: str | None,
    title: str | None,
    input_value: str | None,
    bangumi_subject_urls: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    explicit: list[tuple[str, Any]] = []
    if subject_id is not None:
        explicit.append(("subject_id", subject_id))
    if subject_url:
        explicit.append(("subject_url", subject_url))
    if title:
        explicit.append(("query", title))
    if input_value:
        explicit.append(("input_value", input_value))

    if len(explicit) > 1:
        names = ", ".join(name for name, _ in explicit)
        raise ValueError(f"only one Bangumi selector may be provided at a time: {names}")

    detected_ids = {
        extract_subject_id_from_url(url)
        for url in bangumi_subject_urls
        if extract_subject_id_from_url(url) is not None
    }
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


def build_client(args: argparse.Namespace, scope: str) -> HttpClient:
    return HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir) / scope,
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )


def make_subject_summary_material(domain: str, subject: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    title = subject.get("title_cn") or subject.get("title") or subject.get("name_cn") or subject.get("name") or ""
    summary = subject.get("summary", "") or ""
    return {
        "kind": "bangumi_subject",
        "domain": domain,
        "source": subject.get("url", ""),
        "title": title,
        "content": summary,
        "metadata": {
            "subject_id": subject.get("subject_id"),
            "title": subject.get("title") or subject.get("name", ""),
            "title_cn": subject.get("title_cn") or subject.get("name_cn", ""),
            "url": subject.get("url", ""),
            "resolved_via": resolution.get("match_type"),
            "query": resolution.get("query"),
        },
    }


def normalize_resolved_subject(resolution: dict[str, Any], *, summary: str = "") -> dict[str, Any]:
    best_match = resolution.get("best_match") or {}
    subject_id = resolution.get("subject_id")
    return {
        "subject_id": subject_id,
        "title": best_match.get("name", ""),
        "title_cn": best_match.get("name_cn", ""),
        "date": best_match.get("date", ""),
        "platform": best_match.get("platform", ""),
        "type": best_match.get("type"),
        "url": best_match.get("url", "") or (f"https://bgm.tv/subject/{subject_id}" if subject_id else ""),
        "summary": summary or "",
    }


def collect_web_materials(
    client: HttpClient,
    urls: list[str],
    *,
    extract_body_mode: bool,
    max_chars: int,
    domain: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    materials: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in urls:
        result = _fetch_url(client, url, extract_main=extract_body_mode, max_chars=max_chars)
        if not result.get("success"):
            errors.append(f"{url}: {result.get('error', 'unknown error')}")
            continue
        materials.append(
            {
                "kind": "web_page",
                "domain": domain,
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


def collect_anime_bundle(
    args: argparse.Namespace,
    client: HttpClient,
    selector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str], list[str], int]:
    resolution, exit_code = _resolve_subject(client, domain="anime", limit=10, alternatives_limit=5, **selector)
    warnings: list[str] = []
    errors: list[str] = []
    materials: list[dict[str, Any]] = []
    if exit_code not in (0, 5) or not resolution.get("subject_id"):
        error = resolution.get("error") or {}
        message = error.get("message") or "Bangumi anime subject resolution failed"
        errors.append(f"Bangumi subject: {message}")
        return {}, resolution, materials, warnings, errors, 2

    if exit_code == 5:
        warnings.append(f"Bangumi subject: {(resolution.get('error') or {}).get('message', 'subject match is ambiguous')}")

    subject_id = int(resolution["subject_id"])
    episodes = _fetch_anime_episodes_from_api(client, subject_id, limit=100)
    summary = _fetch_anime_subject_summary(client, subject_id) or ""
    subject = normalize_resolved_subject(resolution, summary=summary)
    materials.append(make_subject_summary_material("anime", subject, resolution))

    if not episodes:
        errors.append("Anime episodes: no episodes found or API request failed")
        return subject, resolution, materials, warnings, errors, 1

    normalized_episodes: list[dict[str, Any]] = []
    for raw_episode in episodes:
        episode = {
            "id": raw_episode.get("id"),
            "sort": raw_episode.get("sort"),
            "name": raw_episode.get("name", ""),
            "name_cn": raw_episode.get("name_cn", ""),
            "desc": raw_episode.get("desc", ""),
            "desc_source": "api",
            "air_date": raw_episode.get("air_date", ""),
            "duration": raw_episode.get("duration", ""),
        }
        if args.fetch_web_detail and raw_episode.get("id"):
            detail = _fetch_anime_episode_detail(client, int(raw_episode["id"]))
            if detail:
                episode["desc"] = detail
                episode["desc_source"] = "web"
        normalized_episodes.append(episode)

    content_lines: list[str] = []
    if summary:
        content_lines.extend(["## Subject Summary", "", summary, ""])
    content_lines.append("## Episodes")
    content_lines.append("")
    for episode in normalized_episodes:
        title = episode["name_cn"] or episode["name"] or f"Episode {episode.get('sort')}"
        content_lines.append(f"### {episode.get('sort')}. {title}")
        if episode.get("desc"):
            content_lines.append(episode["desc"])
        content_lines.append("")

    materials.append(
        {
            "kind": "anime_episodes",
            "domain": "anime",
            "source": subject.get("url", ""),
            "title": subject.get("title_cn") or subject.get("title") or "",
            "content": "\n".join(content_lines).rstrip(),
            "metadata": {
                "subject_id": subject_id,
                "episode_count": len(normalized_episodes),
                "fetch_web_detail": bool(args.fetch_web_detail),
                "resolved_via": resolution.get("match_type"),
            },
            "episodes": normalized_episodes,
        }
    )
    return subject, resolution, materials, warnings, errors, 0 if exit_code == 0 else 1


def collect_game_bundle(
    args: argparse.Namespace,
    client: HttpClient,
    selector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str], list[str], int]:
    resolution, exit_code = _resolve_subject(client, domain="game", limit=10, alternatives_limit=5, **selector)
    warnings: list[str] = []
    errors: list[str] = []
    materials: list[dict[str, Any]] = []
    if exit_code not in (0, 5) or not resolution.get("subject_id"):
        error = resolution.get("error") or {}
        errors.append(f"Bangumi subject: {error.get('message') or 'Bangumi game subject resolution failed'}")
        return {}, resolution, materials, warnings, errors, 2

    if exit_code == 5:
        warnings.append(f"Bangumi subject: {(resolution.get('error') or {}).get('message', 'subject match is ambiguous')}")

    subject_id = int(resolution["subject_id"])
    api_data = _fetch_game_subject_api(client, subject_id)
    if not api_data:
        errors.append("Game plot: Bangumi API returned empty data")
        return {}, resolution, materials, warnings, errors, 2

    web_data = _fetch_game_subject_web(client, subject_id)
    plot_info = _extract_game_plot_elements(api_data, web_data)
    subject = normalize_resolved_subject(resolution, summary=plot_info.get("summary", ""))
    materials.append(make_subject_summary_material("game", subject, resolution))

    content_lines = [
        f"# {plot_info.get('title_cn') or plot_info.get('title') or subject.get('title_cn') or subject.get('title') or ''}",
        "",
        f"- Platform: {plot_info.get('platform') or '未知'}",
        f"- Developer: {plot_info.get('developer') or '未知'}",
        f"- Publisher: {plot_info.get('publisher') or '未知'}",
        f"- Release Date: {plot_info.get('release_date') or '未知'}",
        f"- Genre Tags: {', '.join(plot_info.get('genre_tags') or []) or '无'}",
        f"- Characters: {', '.join(plot_info.get('characters') or []) or '未知'}",
        "",
        "## Summary",
        "",
        plot_info.get("summary") or "暂无简介",
    ]
    guidance = _generate_game_guidance(plot_info) if args.include_guidance else ""
    if guidance:
        content_lines.extend(["", "## Guidance", "", guidance])

    materials.append(
        {
            "kind": "game_plot",
            "domain": "game",
            "source": subject.get("url", ""),
            "title": subject.get("title_cn") or subject.get("title") or "",
            "content": "\n".join(content_lines).rstrip(),
            "metadata": {
                "subject_id": subject_id,
                "resolved_via": resolution.get("match_type"),
                "data_sources": {
                    "api": api_data is not None,
                    "web": bool(web_data.get("summary") or web_data.get("characters") or web_data.get("infobox")),
                },
            },
            "plot_info": plot_info,
            "guidance": guidance,
        }
    )
    return subject, resolution, materials, warnings, errors, 0 if exit_code == 0 else 1


def collect_bangumi_logs_material(
    client: HttpClient,
    *,
    domain: str,
    subject: dict[str, Any],
    include_comments: bool,
    limit: int,
    min_length: int,
) -> tuple[dict[str, Any] | None, list[str], int]:
    subject_id = subject.get("subject_id")
    if not subject_id:
        return None, [f"Bangumi logs: skipped because no {domain} subject_id was resolved"], 1

    subject_info = _fetch_subject_info(client, str(subject_id))
    if not subject_info:
        subject_info = {
            "name": subject.get("title", ""),
            "name_cn": subject.get("title_cn", ""),
            "date": subject.get("date", ""),
        }

    entries = []
    reviews = _fetch_review_entries(client, str(subject_id), limit, 6000, False)
    entries.extend(entry for entry in reviews if getattr(entry, "word_count", 0) >= min_length)
    if len(entries) < limit:
        blogs = _fetch_blog_entries(client, str(subject_id), limit - len(entries), 6000, False)
        entries.extend(entry for entry in blogs if getattr(entry, "word_count", 0) >= min_length)
    if include_comments and len(entries) < limit:
        comments = _fetch_subject_comments(client, str(subject_id), limit - len(entries), 6000, False)
        entries.extend(entry for entry in comments if getattr(entry, "word_count", 0) >= min_length)

    deduped_entries: list[Any] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        key = (entry.kind, entry.url, entry.author, entry.content)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_entries.append(entry)

    if not deduped_entries:
        return None, ["Bangumi logs: no usable reviews/blogs/comments were fetched"], 1

    serialized_entries = [asdict(entry) | {"word_count": entry.word_count} for entry in deduped_entries[:limit]]
    content_lines = []
    for index, entry in enumerate(serialized_entries, start=1):
        content_lines.append(f"## {index}. {entry['kind']}")
        content_lines.append(f"- Author: {entry['author'] or '未知'}")
        content_lines.append(f"- Date: {entry['date'] or '未知'}")
        content_lines.append(f"- URL: {entry['url']}")
        if entry.get("rating") is not None:
            content_lines.append(f"- Rating: {entry['rating']}/10")
        content_lines.extend(["", entry["content"], ""])

    material = {
        "kind": "bangumi_logs",
        "domain": domain,
        "source": f"https://bgm.tv/subject/{subject_id}/reviews",
        "title": f"{subject.get('title_cn') or subject.get('title') or ''} Bangumi logs",
        "content": "\n".join(content_lines).rstrip(),
        "metadata": {
            "subject_id": subject_id,
            "count": len(serialized_entries),
            "include_comments": include_comments,
            "min_length": min_length,
        },
        "subject": {
            "name": subject_info.get("name", ""),
            "name_cn": subject_info.get("name_cn", ""),
            "date": subject_info.get("date", ""),
        },
        "entries": serialized_entries,
    }
    return material, [], 0


def make_book_args(args: argparse.Namespace) -> argparse.Namespace:
    return SimpleNamespace(
        epub=list(args.epub),
        url=list(args.url),
        subject_id=args.subject_id,
        subject_url=args.subject_url,
        title=args.title,
        input=args.input,
        output=None,
        format="json",
        chapters=args.chapters,
        epub_max_chars=args.epub_max_chars,
        metadata_only=args.metadata_only,
        extract_body=args.extract_body,
        web_max_chars=args.web_max_chars,
        cache_dir=str(Path(args.cache_dir) / "book"),
        cache_ttl=args.cache_ttl,
        timeout=args.timeout,
        min_interval=args.min_interval,
    )


def collect_book_domain_bundle(
    args: argparse.Namespace,
    client: HttpClient,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str], dict[str, Any] | None, int]:
    bundle, exit_code = _collect_book_bundle(make_book_args(args), client=client)
    subject = bundle.get("subject") or {}
    materials = []
    for material in bundle.get("materials", []):
        normalized = dict(material)
        normalized["domain"] = "book"
        materials.append(normalized)
    return subject, materials, list(bundle.get("warnings", [])), list(bundle.get("errors", [])), bundle.get("subject_resolution"), exit_code


def collect_bundle(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.domain != "book" and args.epub:
        raise ValueError("--epub is only supported for --domain book")
    if args.domain != "book" and (args.metadata_only or args.chapters):
        raise ValueError("--metadata-only and --chapters are only supported for --domain book")

    bangumi_subject_urls, generic_urls = classify_urls(list(args.url))
    selector, warnings = build_subject_selector(
        subject_id=args.subject_id,
        subject_url=args.subject_url,
        title=args.title,
        input_value=args.input,
        bangumi_subject_urls=bangumi_subject_urls,
    )
    extract_body_mode = True if args.extract_body is None else args.extract_body

    if not any([selector, generic_urls, args.epub]):
        raise ValueError("provide at least one Bangumi selector, generic URL, or EPUB input")

    bundle = {
        "bundle_type": "materials_bundle",
        "format_version": 1,
        "domain": args.domain,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "domain": args.domain,
            "subject_selector": selector or {},
            "urls": list(args.url),
            "generic_urls": generic_urls,
            "epub_files": list(args.epub),
            "include_bangumi_logs": bool(args.include_bangumi_logs),
            "include_comments": bool(args.include_comments),
            "fetch_web_detail": bool(args.fetch_web_detail),
            "metadata_only": bool(args.metadata_only),
            "web_mode": "extract" if extract_body_mode else "raw-html",
        },
        "subject_resolution": None,
        "subject": None,
        "materials": [],
        "warnings": warnings,
        "errors": [],
    }

    domain_exit_code = 0
    if args.domain == "book":
        domain_client = build_client(args, "book-http")
        subject, materials, domain_warnings, domain_errors, resolution, domain_exit_code = collect_book_domain_bundle(args, domain_client)
        bundle["subject"] = subject or None
        bundle["subject_resolution"] = resolution
        bundle["materials"].extend(materials)
        bundle["warnings"].extend(domain_warnings)
        bundle["errors"].extend(domain_errors)
    elif selector:
        domain_client = build_client(args, args.domain)
        if args.domain == "anime":
            subject, resolution, materials, domain_warnings, domain_errors, domain_exit_code = collect_anime_bundle(args, domain_client, selector)
        else:
            subject, resolution, materials, domain_warnings, domain_errors, domain_exit_code = collect_game_bundle(args, domain_client, selector)
        bundle["subject"] = subject or None
        bundle["subject_resolution"] = resolution
        bundle["materials"].extend(materials)
        bundle["warnings"].extend(domain_warnings)
        bundle["errors"].extend(domain_errors)
    else:
        bundle["warnings"].append(f"No Bangumi subject selector provided for {args.domain}; only generic URLs were collected.")

    if generic_urls:
        web_client = build_client(args, "web-content")
        web_materials, web_errors = collect_web_materials(
            web_client,
            generic_urls,
            extract_body_mode=extract_body_mode,
            max_chars=args.web_max_chars,
            domain=args.domain,
        )
        bundle["materials"].extend(web_materials)
        bundle["errors"].extend(web_errors)

    if args.include_bangumi_logs:
        logs_client = build_client(args, "bangumi-logs")
        logs_material, log_warnings, log_exit_code = collect_bangumi_logs_material(
            logs_client,
            domain=args.domain,
            subject=bundle.get("subject") or {},
            include_comments=args.include_comments,
            limit=max(1, args.log_limit),
            min_length=args.log_min_length,
        )
        bundle["warnings"].extend(log_warnings)
        if logs_material:
            bundle["materials"].append(logs_material)
        if log_exit_code != 0 and not logs_material:
            domain_exit_code = max(domain_exit_code, 1)

    if not bundle["materials"]:
        exit_code = 2
    elif bundle["errors"] or domain_exit_code != 0:
        exit_code = 1
    else:
        exit_code = 0
    return bundle, exit_code


def render_material_markdown(material: dict[str, Any]) -> list[str]:
    lines = [f"## {material.get('kind', 'material')}: {material.get('title') or material.get('source') or ''}", ""]
    lines.append(f"- Domain: {material.get('domain', '')}")
    if material.get("source"):
        lines.append(f"- Source: {material['source']}")
    metadata = material.get("metadata") or {}
    for key in ("subject_id", "episode_count", "count", "mode"):
        if metadata.get(key) not in (None, "", False):
            lines.append(f"- {key}: {metadata[key]}")
    lines.append("")
    content = str(material.get("content", "") or "").strip()
    if content:
        lines.append(content)
        lines.append("")
    return lines


def render_markdown(bundle: dict[str, Any]) -> str:
    lines = ["# Materials Bundle", ""]
    lines.append(f"- Domain: {bundle.get('domain', '')}")
    lines.append(f"- Generated At: {bundle.get('generated_at', '')}")
    lines.append(f"- Material Count: {len(bundle.get('materials', []))}")
    lines.append("")

    subject = bundle.get("subject")
    if subject:
        lines.extend(["## Subject", ""])
        lines.append(f"- Subject ID: {subject.get('subject_id') or ''}")
        lines.append(f"- Title: {subject.get('title_cn') or subject.get('title') or ''}")
        if subject.get("title") and subject.get("title_cn"):
            lines.append(f"- Original Title: {subject.get('title')}")
        if subject.get("url"):
            lines.append(f"- URL: {subject.get('url')}")
        if subject.get("date"):
            lines.append(f"- Date: {subject.get('date')}")
        lines.append("")
        if subject.get("summary"):
            lines.extend(["### Summary", "", subject["summary"], ""])

    for material in bundle.get("materials", []):
        lines.extend(render_material_markdown(material))

    warnings = bundle.get("warnings") or []
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    errors = bundle.get("errors") or []
    if errors:
        lines.extend(["## Errors", ""])
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
        bundle, exit_code = collect_bundle(args)
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
