#!/usr/bin/env python3
"""
Resolve a Bangumi subject from either a subject URL or a title query.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from script_http import HttpClient, RequestError, get_logger, setup_logging

BANGUMI_API_BASE = "https://api.bgm.tv/v0"
LOGGER = get_logger("resolve_subject")
SUBJECT_TYPE_MAP = {
    "book": 1,
    "anime": 2,
    "music": 3,
    "game": 4,
    "real": 6,
}
VALID_HOSTS = {"bgm.tv", "bangumi.tv", "chii.in"}
URL_PATH_PATTERN = re.compile(r"/(?:subject|anime|book|music|game|real)/(\d+)(?:/|$)")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_title(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalize_space(normalized)
    normalized = re.sub(r"[\s\-_:：·'\"“”‘’!！?？,，.。/／\\()（）\[\]{}<>《》]+", "", normalized)
    return normalized.casefold()


def normalize_subject(subject: dict[str, Any]) -> dict[str, Any]:
    subject_id = subject.get("id")
    return {
        "id": subject_id,
        "name": subject.get("name", "") or "",
        "name_cn": subject.get("name_cn", "") or "",
        "type": subject.get("type"),
        "date": subject.get("date", "") or "",
        "platform": subject.get("platform", "") or "",
        "url": f"https://bgm.tv/subject/{subject_id}" if subject_id else "",
    }


def extract_subject_id_from_url(raw: str) -> int | None:
    if not raw:
        return None
    candidate = raw.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    if host not in VALID_HOSTS:
        return None

    match = URL_PATH_PATTERN.search(parsed.path)
    if not match:
        return None
    return int(match.group(1))


def score_subject(query: str, subject: dict[str, Any]) -> tuple[float, bool]:
    query_norm = normalize_title(query)
    if not query_norm:
        return 0.0, False

    best_score = 0.0
    exact_match = False
    names = [subject.get("name_cn", ""), subject.get("name", "")]
    for index, raw_name in enumerate(names):
        name_norm = normalize_title(str(raw_name or ""))
        if not name_norm:
            continue

        if name_norm == query_norm:
            score = 120.0 - index
            best_score = max(best_score, score)
            exact_match = True
            continue
        if query_norm in name_norm:
            best_score = max(best_score, 96.0 - index)
            continue
        if name_norm.startswith(query_norm) or query_norm.startswith(name_norm):
            best_score = max(best_score, 92.0 - index)
            continue

        ratio = SequenceMatcher(None, query_norm, name_norm).ratio() * 100
        best_score = max(best_score, ratio)

    return round(best_score, 2), exact_match


def rank_subjects(query: str, subjects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for raw in subjects:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        subject = normalize_subject(raw)
        match_score, exact_match = score_subject(query, subject)
        subject["match_score"] = match_score
        subject["exact_match"] = exact_match
        ranked.append(subject)

    ranked.sort(
        key=lambda item: (
            -float(item.get("match_score", 0.0)),
            0 if item.get("exact_match") else 1,
            0 if item.get("name_cn") else 1,
            str(item.get("date") or "9999-99-99"),
            int(item.get("id") or 0),
        )
    )
    return ranked


def is_ambiguous_match(ranked: list[dict[str, Any]]) -> bool:
    if not ranked:
        return False
    top = ranked[0]
    top_score = float(top.get("match_score", 0.0))
    if top_score < 55:
        return True
    if len(ranked) < 2:
        return False

    second = ranked[1]
    second_score = float(second.get("match_score", 0.0))
    if top.get("exact_match") and second.get("exact_match") and top.get("id") != second.get("id"):
        return True
    if not top.get("exact_match") and second_score >= 70 and top_score - second_score <= 3:
        return True
    return False


def post_json(client: HttpClient, url: str, *, body: dict[str, Any], params: dict[str, Any] | None = None) -> Any:
    client.rate_limiter.wait()
    client.logger.info("POST %s", url)
    try:
        response = client.session.post(url, params=params, json=body, timeout=client.timeout)
    except requests.RequestException as exc:
        raise RequestError(f"request failed: {exc}", url=url) from exc

    if response.status_code >= 400:
        raise RequestError(
            f"unexpected HTTP status {response.status_code}",
            url=url,
            status_code=response.status_code,
        )

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"

    try:
        return response.json()
    except ValueError as exc:
        raise RequestError(f"invalid JSON response: {exc}", url=url) from exc


def fetch_subject_detail(client: HttpClient, subject_id: int) -> dict[str, Any]:
    url = f"{BANGUMI_API_BASE}/subjects/{subject_id}"
    return client.get_json(url)


def search_subjects(client: HttpClient, query: str, *, domain: str | None, limit: int) -> list[dict[str, Any]]:
    url = f"{BANGUMI_API_BASE}/search/subjects"
    body: dict[str, Any] = {
        "keyword": query,
        "sort": "match",
    }
    if domain:
        body["filter"] = {"type": [SUBJECT_TYPE_MAP[domain]]}
    payload = post_json(client, url, body=body, params={"limit": limit})
    return payload.get("data", []) if isinstance(payload, dict) else []


def build_result(
    *,
    query: str,
    match_type: str,
    best_match: dict[str, Any] | None,
    alternatives: list[dict[str, Any]],
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "query": query,
        "subject_id": best_match.get("id") if best_match else None,
        "match_type": match_type,
        "best_match": best_match,
        "alternatives": alternatives,
        "error": error,
    }


def parse_input(args: argparse.Namespace) -> tuple[str, str]:
    if args.subject_url:
        return args.subject_url, "url"
    if args.query:
        return args.query, "search"

    raw = args.input.strip()
    return (raw, "url") if extract_subject_id_from_url(raw) else (raw, "search")


def add_subject_resolution_arguments(
    parser: argparse.ArgumentParser,
    *,
    require_one: bool = True,
    include_domain: bool = True,
) -> argparse._MutuallyExclusiveGroup:
    input_group = parser.add_mutually_exclusive_group(required=require_one)
    input_group.add_argument("--subject-id", type=int, help="Bangumi subject ID")
    input_group.add_argument("--subject-url", type=str, help="Bangumi subject URL")
    input_group.add_argument("--query", type=str, help="Title query to search")
    input_group.add_argument("--input", type=str, help="Auto-detect Bangumi URL or title query")
    if include_domain:
        parser.add_argument("--domain", choices=sorted(SUBJECT_TYPE_MAP), help="Optional subject domain filter for title search")
    return input_group


def _resolve_from_url(client: HttpClient, query: str) -> tuple[dict[str, Any], int]:
    subject_id = extract_subject_id_from_url(query)
    if not subject_id:
        return (
            build_result(
                query=query,
                match_type="url",
                best_match=None,
                alternatives=[],
                error={"code": "invalid_url", "message": "无法从输入中提取 Bangumi subject_id"},
            ),
            2,
        )

    try:
        detail = fetch_subject_detail(client, subject_id)
    except RequestError as exc:
        return (
            build_result(
                query=query,
                match_type="url",
                best_match=None,
                alternatives=[],
                error={"code": "http_error", "message": f"拉取条目详情失败: {exc}"},
            ),
            4,
        )

    best_match = normalize_subject(detail)
    return (
        build_result(
            query=query,
            match_type="url",
            best_match=best_match,
            alternatives=[],
        ),
        0,
    )


def _resolve_from_search(
    client: HttpClient,
    query: str,
    *,
    domain: str | None,
    limit: int,
    alternatives_limit: int,
) -> tuple[dict[str, Any], int]:
    try:
        results = search_subjects(client, query, domain=domain, limit=limit)
    except RequestError as exc:
        return (
            build_result(
                query=query,
                match_type="search",
                best_match=None,
                alternatives=[],
                error={"code": "http_error", "message": f"搜索条目失败: {exc}"},
            ),
            4,
        )

    ranked = rank_subjects(query, results)
    if not ranked:
        return (
            build_result(
                query=query,
                match_type="search",
                best_match=None,
                alternatives=[],
                error={"code": "no_match", "message": "未找到可用的 Bangumi 条目匹配"},
            ),
            3,
        )

    best_match = ranked[0]
    alternatives = ranked[1 : 1 + max(0, alternatives_limit)]
    ambiguous = is_ambiguous_match(ranked)
    return (
        build_result(
            query=query,
            match_type="search",
            best_match=best_match,
            alternatives=alternatives,
            error=(
                {
                    "code": "ambiguous_match",
                    "message": "匹配结果存在歧义，请结合候选列表确认 subject_id",
                }
                if ambiguous
                else None
            ),
        ),
        5 if ambiguous else 0,
    )


def resolve_subject(
    client: HttpClient,
    *,
    subject_id: int | None = None,
    subject_url: str | None = None,
    query: str | None = None,
    input_value: str | None = None,
    domain: str | None = None,
    limit: int = 10,
    alternatives_limit: int = 5,
) -> tuple[dict[str, Any], int]:
    if subject_id is not None:
        try:
            detail = fetch_subject_detail(client, int(subject_id))
        except RequestError as exc:
            return (
                build_result(
                    query=str(subject_id),
                    match_type="subject_id",
                    best_match=None,
                    alternatives=[],
                    error={"code": "http_error", "message": f"拉取条目详情失败: {exc}"},
                ),
                4,
            )
        best_match = normalize_subject(detail)
        return (
            build_result(
                query=str(subject_id),
                match_type="subject_id",
                best_match=best_match,
                alternatives=[],
            ),
            0,
        )

    if subject_url:
        return _resolve_from_url(client, subject_url)
    if query:
        return _resolve_from_search(
            client,
            query,
            domain=domain,
            limit=limit,
            alternatives_limit=alternatives_limit,
        )
    if input_value:
        match_query, match_type = parse_input(
            argparse.Namespace(subject_url=None, query=None, input=input_value)
        )
        if match_type == "url":
            return _resolve_from_url(client, match_query)
        return _resolve_from_search(
            client,
            match_query,
            domain=domain,
            limit=limit,
            alternatives_limit=alternatives_limit,
        )

    raise ValueError("one of subject_id, subject_url, query, or input_value is required")


def resolve_subject_from_args(
    args: argparse.Namespace,
    client: HttpClient,
    *,
    default_domain: str | None = None,
    limit: int | None = None,
    alternatives_limit: int | None = None,
) -> tuple[dict[str, Any], int]:
    return resolve_subject(
        client,
        subject_id=getattr(args, "subject_id", None),
        subject_url=getattr(args, "subject_url", None),
        query=getattr(args, "query", None),
        input_value=getattr(args, "input", None),
        domain=getattr(args, "domain", None) or default_domain,
        limit=limit if limit is not None else getattr(args, "limit", 10),
        alternatives_limit=(
            alternatives_limit
            if alternatives_limit is not None
            else getattr(args, "alternatives_limit", 5)
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve Bangumi subject ID from URL or title")
    add_subject_resolution_arguments(parser, require_one=True, include_domain=True)
    parser.add_argument("--limit", type=int, default=10, help="Max search results to fetch")
    parser.add_argument("--alternatives-limit", type=int, default=5, help="Max alternative matches to include")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--cache-dir", default=".cache/subject-resolver", help="GET response cache directory")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600, help="Cache TTL in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="Read timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.6, help="Minimum interval between requests")
    return parser


def emit_result(payload: dict[str, Any], *, output: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
        LOGGER.info("output written to %s", output)
        return
    sys.stdout.write(text)


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
    payload, exit_code = resolve_subject_from_args(args, client)
    emit_result(payload, output=args.output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
