#!/usr/bin/env python3
"""
Read EPUB file and extract metadata/chapter text.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT

from script_logging import get_logger, setup_logging


LOGGER = get_logger("read_epub")


def extract_metadata_value(book: epub.EpubBook, namespace: str, key: str) -> str:
    values = book.get_metadata(namespace, key)
    if not values:
        return ""
    first = values[0][0]
    return str(first).strip() if first else ""


def extract_chapters(book: epub.EpubBook) -> list[dict[str, str]]:
    chapters: list[dict[str, str]] = []
    for item in book.get_items():
        if item.get_type() != ITEM_DOCUMENT or not isinstance(item, epub.EpubHtml):
            continue
        raw = item.get_content()
        text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
        chapters.append(
            {
                "id": item.id or "",
                "file_name": item.file_name or "",
                "title": str(item.title or "").strip(),
                "content": text,
            }
        )
    return chapters


def clean_html_to_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n\n".join(lines)


def extract_metadata(book: epub.EpubBook) -> dict[str, str]:
    authors = [str(author[0]).strip() for author in book.get_metadata("DC", "creator") if author and author[0]]
    metadata = {
        "title": str(book.title or "").strip(),
        "author": ", ".join(authors),
        "language": extract_metadata_value(book, "DC", "language"),
        "publisher": extract_metadata_value(book, "DC", "publisher"),
        "date": extract_metadata_value(book, "DC", "date"),
        "identifier": extract_metadata_value(book, "DC", "identifier"),
        "description": extract_metadata_value(book, "DC", "description"),
    }
    return metadata


def parse_chapter_selection(raw: str | None, total: int) -> tuple[int, int]:
    if not raw or raw.lower() == "all":
        return 0, total
    match = re.fullmatch(r"(\d+)-(\d+)", raw.strip())
    if not match:
        raise ValueError(f"invalid chapter range: {raw}")
    start = int(match.group(1))
    end = int(match.group(2))
    if start < 1 or end < start:
        raise ValueError(f"invalid chapter range: {raw}")
    return start - 1, min(end, total)


def format_metadata(metadata: dict[str, str]) -> str:
    lines = ["# Book Metadata", ""]
    for key, value in metadata.items():
        if value:
            lines.append(f"- **{key.title()}**: {value}")
    return "\n".join(lines).rstrip() + "\n"


def build_output(metadata: dict[str, str], chapters: list[dict[str, str]], max_chars: int) -> str:
    lines = ["# Book Content", ""]
    for key in ("title", "author", "language", "publisher", "date"):
        if metadata.get(key):
            lines.append(f"## {key.title()}: {metadata[key]}")
    if metadata.get("description"):
        lines.extend(["", "## Description", "", metadata["description"]])
    lines.extend(["", "---", ""])

    total = len(chapters)
    for index, chapter in enumerate(chapters, start=1):
        title = chapter["title"] or f"Chapter {index}"
        content = clean_html_to_text(chapter["content"])
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n\n[... truncated ...]"
        lines.append(f"## {title}")
        lines.append("")
        lines.append(content or "[空章节]")
        lines.append("")
        lines.append("---")
        lines.append("")
        if index % 5 == 0 or index == total:
            LOGGER.info("processed %s/%s chapters", index, total)
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read EPUB file and extract content")
    parser.add_argument("--input", type=str, required=True, help="Input EPUB file path")
    parser.add_argument("--output", type=str, help="Output Markdown file path")
    parser.add_argument("--chapters", type=str, help="Chapter range, e.g. '1-5' or 'all'")
    parser.add_argument("--max-chars", type=int, default=50000, help="Max characters per chapter (0 for unlimited)")
    parser.add_argument("--metadata-only", action="store_true", help="Only extract metadata")
    return parser


def main() -> int:
    setup_logging()
    args = build_parser().parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        LOGGER.error("file not found: %s", input_path)
        return 2
    if input_path.suffix.lower() != ".epub":
        LOGGER.warning("input does not look like an EPUB: %s", input_path.name)

    LOGGER.info("reading EPUB: %s", input_path)
    try:
        book = epub.read_epub(str(input_path))
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("failed to read EPUB: %s", exc)
        return 3

    metadata = extract_metadata(book)
    if args.metadata_only:
        output = format_metadata(metadata)
    else:
        chapters = extract_chapters(book)
        if not chapters:
            LOGGER.error("no readable document chapters found in EPUB")
            return 4
        try:
            start, end = parse_chapter_selection(args.chapters, len(chapters))
        except ValueError as exc:
            LOGGER.error(str(exc))
            return 2
        selected = chapters[start:end]
        if not selected:
            LOGGER.error("selected chapter range is empty")
            return 2
        LOGGER.info("selected %s/%s chapters", len(selected), len(chapters))
        output = build_output(metadata, selected, args.max_chars)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        LOGGER.info("written to %s", args.output)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
