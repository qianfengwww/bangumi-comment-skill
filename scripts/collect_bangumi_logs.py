#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag
from script_logging import get_logger, setup_logging
from script_http import HttpClient

BASE = "https://bangumi.tv"
LOGGER = get_logger("collect_bangumi_logs")

DOMAIN_PATHS = {
    "anime": "/anime/blog",
    "book": "/book/blog",
    "game": "/game/blog",
}

CLIENT: HttpClient | None = None


@dataclass
class BlogSample:
    domain: str
    page_no: int
    blog_id: int
    url: str
    title: str
    author: str
    author_url: str
    subject_title: str
    subject_url: str
    date_text: str
    reading_time: str
    char_count: int
    paragraph_count: int
    heading_count: int
    excerpt: str
    opening_line: str
    closing_line: str
    tags_or_notes: list[str]
    structure_notes: list[str]


@dataclass
class ListEntry:
    domain: str
    page_no: int
    title: str
    url: str
    author: str
    author_url: str
    subject_title: str
    subject_url: str
    date_text: str
    preview: str


def fetch(url: str, retries: int = 3, sleep_s: float = 0.25) -> str:
    if CLIENT is None:
        raise RuntimeError("HTTP client is not configured")
    _ = retries, sleep_s
    return CLIENT.get_text(url)


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\r", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(" \n·")


def collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", clean_text(text)).strip()


def split_paragraphs_from_entry(entry_content: Tag) -> list[str]:
    p_tags = [collapse_spaces(p.get_text(" ", strip=True)) for p in entry_content.select(":scope > p")]
    p_tags = [p for p in p_tags if p]
    if p_tags:
        return p_tags

    parts: list[str] = []
    buf: list[str] = []
    br_run = 0

    def flush() -> None:
        nonlocal buf, br_run
        text = collapse_spaces(" ".join(buf))
        if text:
            parts.append(text)
        buf = []
        br_run = 0

    for node in entry_content.children:
        if isinstance(node, NavigableString):
            text = collapse_spaces(str(node))
            if text:
                buf.append(text)
            continue

        if not isinstance(node, Tag):
            continue

        if node.name == "br":
            br_run += 1
            if br_run >= 2:
                flush()
            continue

        br_run = 0

        if node.name == "img":
            flush()
            continue

        if node.name in {"hr"}:
            flush()
            continue

        if node.name in {"ul", "ol"}:
            flush()
            for li in node.select("li"):
                li_text = collapse_spaces(li.get_text(" ", strip=True))
                if li_text:
                    parts.append(li_text)
            continue

        text = collapse_spaces(node.get_text(" ", strip=True))
        if not text:
            continue

        if node.name in {"div", "p", "blockquote", "pre"}:
            flush()
            parts.append(text)
            continue

        buf.append(text)

    flush()

    cleaned: list[str] = []
    for part in parts:
        part = collapse_spaces(part)
        if not part:
            continue
        cleaned.append(part)
    return cleaned


def analyze_structure(title: str, paragraphs: list[str]) -> tuple[int, list[str]]:
    notes: list[str] = []
    heading_count = 0

    for p in paragraphs:
        if len(p) <= 22 and len(re.findall(r"[，。！？,.!?]", p)) <= 1:
            heading_count += 1

    if heading_count >= 2:
        notes.append("存在明显小标题分段")
    if len(paragraphs) >= 7:
        notes.append("段落推进较充分")
    if any(len(p) > 180 for p in paragraphs):
        notes.append("存在长段展开")
    if any("剧透" in p or "防剧透" in p for p in paragraphs[:3]):
        notes.append("含剧透提示")
    if any(k in paragraphs[0][:40] for k in ["我", "读完", "看完", "先说结论", "先说"] ) if paragraphs else False:
        notes.append("开头带个人体验或结论")
    if len(title) <= 12:
        notes.append("标题较短促")
    elif len(title) >= 20:
        notes.append("标题偏完整判断句")

    return heading_count, notes


def parse_subject(soup: BeautifulSoup, title: str) -> tuple[str, str]:
    related = soup.select_one(".entry-related-subjects .subject-card .title a[href^='/subject/']")
    if related:
        return collapse_spaces(related.get_text(" ", strip=True)), urljoin(BASE, related.get("href", ""))

    for a in soup.select("a[href^='/subject/']"):
        href = a.get("href", "")
        txt = collapse_spaces(a.get_text(" ", strip=True))
        if txt and txt != title:
            return txt, urljoin(BASE, href)

    return "", ""


def parse_detail(url: str, domain: str, page_no: int) -> Optional[BlogSample]:
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("#viewEntry.entry-container") or soup.select_one(".entry-container")
    if not container:
        return None

    title_node = container.select_one(".header h1.title")
    title = collapse_spaces(title_node.get_text(" ", strip=True) if title_node else "")
    if not title:
        return None

    author_link = container.select_one(".author .title a.avatar.l") or container.select_one(".author .title a")
    author = collapse_spaces(author_link.get_text(" ", strip=True) if author_link else "")
    author_url = urljoin(BASE, author_link.get("href", "")) if author_link else ""

    time_block = container.select_one(".header .tools .time")
    date_text = ""
    reading_time = ""
    if time_block:
        raw = collapse_spaces(time_block.get_text(" ", strip=True))
        parts = [collapse_spaces(x) for x in raw.split("·") if collapse_spaces(x)]
        if parts:
            date_text = parts[0]
        if len(parts) > 1:
            reading_time = parts[1]

    tag_nodes = container.select(".header .tools .tags .badge_tag")
    tags = [collapse_spaces(n.get_text(" ", strip=True)) for n in tag_nodes if collapse_spaces(n.get_text(" ", strip=True))]

    entry_content = container.select_one("#entry_content")
    if not entry_content:
        return None

    paragraphs = split_paragraphs_from_entry(entry_content)
    paragraphs = [p for p in paragraphs if p and not p.startswith("http")]
    char_count = sum(len(p) for p in paragraphs)
    paragraph_count = len(paragraphs)
    heading_count, structure_notes = analyze_structure(title, paragraphs)

    subject_title, subject_url = parse_subject(soup, title)

    excerpt = "\n\n".join(paragraphs[:2])[:420]
    opening_line = paragraphs[0][:180] if paragraphs else ""
    closing_line = paragraphs[-1][:180] if paragraphs else ""
    blog_id_match = re.search(r"/blog/(\d+)", url)
    if not blog_id_match:
        return None

    tags_or_notes = []
    for item in [*tags, *structure_notes]:
        if item and item not in tags_or_notes:
            tags_or_notes.append(item)

    return BlogSample(
        domain=domain,
        page_no=page_no,
        blog_id=int(blog_id_match.group(1)),
        url=url,
        title=title,
        author=author,
        author_url=author_url,
        subject_title=subject_title,
        subject_url=subject_url,
        date_text=date_text,
        reading_time=reading_time,
        char_count=char_count,
        paragraph_count=paragraph_count,
        heading_count=heading_count,
        excerpt=excerpt,
        opening_line=opening_line,
        closing_line=closing_line,
        tags_or_notes=tags_or_notes,
        structure_notes=structure_notes,
    )


def page_url(domain: str, page_no: int) -> str:
    path = DOMAIN_PATHS[domain]
    if page_no == 1:
        return urljoin(BASE, path)
    return urljoin(BASE, f"{path}/{page_no}.html")


def iter_list_entries(domain: str, max_pages: int) -> Iterable[ListEntry]:
    for page_no in range(1, max_pages + 1):
        html = fetch(page_url(domain, page_no))
        soup = BeautifulSoup(html, "lxml")
        items = soup.select("#entry_list .item")
        if not items:
            break

        for item in items:
            title_link = item.select_one(".entry .title a.l")
            if not title_link:
                continue

            detail_url = urljoin(BASE, title_link.get("href", ""))
            title = collapse_spaces(title_link.get_text(" ", strip=True))
            time_row = item.select_one(".tools .time")
            author = ""
            author_url = ""
            subject_title = ""
            subject_url = ""
            date_text = ""
            if time_row:
                user_link = time_row.select_one("a[href^='/user/']")
                subject_link = time_row.select_one("a[href^='/subject/']")
                if user_link:
                    author = collapse_spaces(user_link.get_text(" ", strip=True))
                    author_url = urljoin(BASE, user_link.get("href", ""))
                if subject_link:
                    subject_title = collapse_spaces(subject_link.get_text(" ", strip=True))
                    subject_url = urljoin(BASE, subject_link.get("href", ""))
                raw = collapse_spaces(time_row.get_text(" ", strip=True))
                segs = [collapse_spaces(x) for x in raw.split("·") if collapse_spaces(x)]
                if len(segs) >= 2:
                    date_text = segs[-2]
                elif segs:
                    date_text = segs[-1]

            preview = collapse_spaces(item.select_one(".entry .content").get_text(" ", strip=True) if item.select_one(".entry .content") else "")
            yield ListEntry(
                domain=domain,
                page_no=page_no,
                title=title,
                url=detail_url,
                author=author,
                author_url=author_url,
                subject_title=subject_title,
                subject_url=subject_url,
                date_text=date_text,
                preview=preview,
            )


def collect(domain: str, target: int, max_pages: int, min_chars: int, min_paragraphs: int) -> tuple[list[BlogSample], dict]:
    accepted: list[BlogSample] = []
    seen: set[int] = set()
    scanned = 0
    rejected = 0
    last_page = 0

    for entry in iter_list_entries(domain, max_pages=max_pages):
        last_page = max(last_page, entry.page_no)
        match = re.search(r"/blog/(\d+)", entry.url)
        if not match:
            continue
        blog_id = int(match.group(1))
        if blog_id in seen:
            continue
        seen.add(blog_id)
        scanned += 1

        try:
            sample = parse_detail(entry.url, domain=domain, page_no=entry.page_no)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("failed %s: %s", entry.url, exc)
            continue

        if not sample:
            continue

        if not sample.subject_title and entry.subject_title:
            sample.subject_title = entry.subject_title
            sample.subject_url = entry.subject_url
        if not sample.author and entry.author:
            sample.author = entry.author
            sample.author_url = entry.author_url
        if not sample.date_text and entry.date_text:
            sample.date_text = entry.date_text

        if sample.char_count >= min_chars and sample.paragraph_count > min_paragraphs:
            accepted.append(sample)
        else:
            rejected += 1

        if scanned % 25 == 0:
            LOGGER.info(
                "progress domain=%s scanned=%s accepted=%s rejected=%s last_page=%s",
                domain,
                scanned,
                len(accepted),
                rejected,
                last_page,
            )

        if len(accepted) >= target:
            break

    char_counts = [x.char_count for x in accepted]
    para_counts = [x.paragraph_count for x in accepted]
    heading_counts = [x.heading_count for x in accepted]

    stats = {
        "domain": domain,
        "target": target,
        "accepted": len(accepted),
        "scanned": scanned,
        "rejected": rejected,
        "pages_scanned": last_page,
        "min_chars": min_chars,
        "min_paragraphs": min_paragraphs,
        "avg_chars": round(statistics.mean(char_counts), 2) if char_counts else 0,
        "median_chars": round(statistics.median(char_counts), 2) if char_counts else 0,
        "avg_paragraphs": round(statistics.mean(para_counts), 2) if para_counts else 0,
        "median_paragraphs": round(statistics.median(para_counts), 2) if para_counts else 0,
        "avg_headings": round(statistics.mean(heading_counts), 2) if heading_counts else 0,
        "max_chars": max(char_counts) if char_counts else 0,
        "min_chars_observed": min(char_counts) if char_counts else 0,
        "max_paragraphs": max(para_counts) if para_counts else 0,
        "min_paragraphs_observed": min(para_counts) if para_counts else 0,
        "first_sample_date": accepted[0].date_text if accepted else "",
        "last_sample_date": accepted[-1].date_text if accepted else "",
    }
    return accepted, stats


def write_outputs(out_dir: Path, samples: list[BlogSample], stats: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "samples.jsonl").write_text(
        "\n".join(json.dumps(asdict(s), ensure_ascii=False) for s in samples) + ("\n" if samples else ""),
        encoding="utf-8",
    )
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    note_freq: dict[str, int] = {}
    tag_freq: dict[str, int] = {}
    for sample in samples:
        for note in sample.structure_notes:
            note_freq[note] = note_freq.get(note, 0) + 1
        for tag in sample.tags_or_notes:
            if tag in sample.structure_notes:
                continue
            tag_freq[tag] = tag_freq.get(tag, 0) + 1

    top_notes = sorted(note_freq.items(), key=lambda x: (-x[1], x[0]))[:10]
    top_tags = sorted(tag_freq.items(), key=lambda x: (-x[1], x[0]))[:10]
    top_samples = sorted(samples, key=lambda s: (-s.char_count, -s.paragraph_count, s.blog_id))[:12]

    lines = [
        f"# {stats['domain']} 日志样本总结",
        "",
        f"- 目标样本数：{stats['target']}",
        f"- 实际合格数：{stats['accepted']}",
        f"- 扫描篇数：{stats['scanned']}",
        f"- 拒绝篇数：{stats['rejected']}",
        f"- 扫描页数：{stats.get('pages_scanned', 0)}",
        f"- 平均字数：{stats.get('avg_chars', 0)}",
        f"- 中位数字数：{stats.get('median_chars', 0)}",
        f"- 平均段落数：{stats.get('avg_paragraphs', 0)}",
        f"- 中位数段落：{stats.get('median_paragraphs', 0)}",
        f"- 平均小标题数：{stats.get('avg_headings', 0)}",
        f"- 样本日期范围：{stats.get('first_sample_date', '')} → {stats.get('last_sample_date', '')}",
        "",
        "## 高频结构特征",
    ]
    if top_notes:
        lines.extend([f"- {name}: {count}" for name, count in top_notes])
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 常见标签"])
    if top_tags:
        lines.extend([f"- {name}: {count}" for name, count in top_tags])
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 代表样本（按字数优先）", ""])
    for sample in top_samples:
        lines.extend(
            [
                f"### {sample.title}",
                f"- URL: {sample.url}",
                f"- 作者: {sample.author}",
                f"- 条目: {sample.subject_title or '未识别'}",
                f"- 字数 / 段落 / 小标题: {sample.char_count} / {sample.paragraph_count} / {sample.heading_count}",
                f"- 开头摘录: {sample.opening_line}",
                f"- 结尾摘录: {sample.closing_line}",
                f"- 结构备注: {', '.join(sample.structure_notes) if sample.structure_notes else '无'}",
                "",
            ]
        )

    (out_dir / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=sorted(DOMAIN_PATHS))
    parser.add_argument("--target", type=int, default=120)
    parser.add_argument("--max-pages", type=int, default=60)
    parser.add_argument("--min-chars", type=int, default=800)
    parser.add_argument("--min-paragraphs", type=int, default=3)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cache-dir", default=".cache/bangumi-collect")
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args()

    global CLIENT
    CLIENT = HttpClient(
        timeout=(10.0, float(args.timeout)),
        min_interval=args.min_interval,
        cache_dir=Path(args.cache_dir),
        cache_ttl_seconds=args.cache_ttl,
        logger=LOGGER,
    )

    samples, stats = collect(
        domain=args.domain,
        target=args.target,
        max_pages=args.max_pages,
        min_chars=args.min_chars,
        min_paragraphs=args.min_paragraphs,
    )
    write_outputs(Path(args.output_dir), samples, stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if samples else 1


if __name__ == "__main__":
    raise SystemExit(main())
