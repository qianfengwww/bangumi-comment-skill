#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
import re

DOMAIN_LABELS = {
    "anime": "动画",
    "book": "书籍",
    "game": "游戏",
}

STRUCTURE_NOTE_ORDER = [
    "段落推进较充分",
    "存在长段展开",
    "存在明显小标题分段",
    "标题偏完整判断句",
    "开头带个人体验或立场",
    "开头带个人体验或结论",
    "标题较短促",
    "含剧透提示",
]


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def classify_opening(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return "未提取到有效开头"
    if any(k in t[:40] for k in ["原载", "转载", "译者", "参考文献", "链接", "采访"]):
        return "资料 / 转载 / 访谈切入"
    if re.search(r"(第.?[0-9一二三四五六七八九十百]+[集卷章话]|ep\s*\d+|EP\s*\d+|周目|路线|线路)", t):
        return "单集 / 单卷 / 单线切入"
    if any(k in t[:20] for k in ["先说结论", "先说", "结论"]):
        return "结论先行"
    if re.search(r"(看完|读完|通关|打完|补完|玩完|追完)", t):
        return "个人体验起手"
    if t.startswith("我") or "我" in t[:8]:
        return "我感受先行"
    if any(k in t[:24] for k in ["为什么", "是否", "问题", "如果"]):
        return "问题切入"
    if any(k in t[:20] for k in ["这部", "这本", "这作", "本作", "作品"]):
        return "总判断切入"
    return "场景 / 情绪 / 句子气氛切入"


def classify_title(title: str) -> str:
    t = (title or "").strip()
    if len(t) <= 12:
        return "短标题"
    if any(x in t for x in ["——", "：", ":", "？", "?", "｜", "|"]):
        return "判断句 / 解释型长标题"
    return "中等长度标题"


def pick_representatives(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    sorted_rows = sorted(rows, key=lambda x: (-x.get("char_count", 0), -x.get("paragraph_count", 0), x.get("title", "")))
    reps: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict) -> None:
        key = (row.get("title", ""), row.get("author", ""))
        if key in seen:
            return
        seen.add(key)
        reps.append(row)

    for row in sorted_rows[:3]:
        add(row)

    by_balance = sorted(
        rows,
        key=lambda x: (
            abs(x.get("char_count", 0) - statistics.median([r.get("char_count", 0) for r in rows])),
            abs(x.get("paragraph_count", 0) - statistics.median([r.get("paragraph_count", 0) for r in rows])),
        ),
    )
    for row in by_balance[:5]:
        add(row)
        if len(reps) >= 6:
            break

    return reps[:6]


def build_markdown(domain: str, rows: list[dict], stats: dict) -> str:
    label = DOMAIN_LABELS.get(domain, domain)
    note_counter = Counter()
    opening_counter = Counter()
    title_counter = Counter()

    for row in rows:
        notes = row.get("structure_notes") or []
        note_counter.update(notes)
        opening_counter.update([classify_opening(row.get("opening_line", ""))])
        title_counter.update([classify_title(row.get("title", ""))])

    reps = pick_representatives(rows)

    lines: list[str] = []
    lines.append(f"# {label}日志样本总结")
    lines.append("")
    lines.append("## 样本规模")
    lines.append(f"- 合格样本数：{stats.get('accepted', len(rows))}")
    lines.append(f"- 扫描篇数：{stats.get('scanned', 0)}")
    lines.append(f"- 拒绝篇数：{stats.get('rejected', 0)}")
    if stats.get("pages_scanned") is not None:
        lines.append(f"- 扫描页数：{stats.get('pages_scanned', 0)}")
    lines.append(f"- 平均字数：{stats.get('avg_chars', 0)}")
    lines.append(f"- 中位字数：{stats.get('median_chars', 0)}")
    lines.append(f"- 平均段落数：{stats.get('avg_paragraphs', 0)}")
    lines.append(f"- 中位段落数：{stats.get('median_paragraphs', 0)}")
    lines.append(f"- 平均小标题数：{stats.get('avg_headings', 0)}")
    if stats.get("first_sample_date"):
        lines.append(f"- 时间范围：{stats.get('first_sample_date')} → {stats.get('last_sample_date', '')}")
    lines.append("")

    lines.append("## 高频结构特征")
    for note in STRUCTURE_NOTE_ORDER:
        if note_counter.get(note):
            lines.append(f"- {note}：{note_counter[note]}")
    for note, count in note_counter.most_common():
        if note not in STRUCTURE_NOTE_ORDER:
            lines.append(f"- {note}：{count}")
    lines.append("")

    lines.append("## 常见开头方式")
    for name, count in opening_counter.most_common():
        lines.append(f"- {name}：{count}")
    lines.append("")

    lines.append("## 标题倾向")
    for name, count in title_counter.most_common():
        lines.append(f"- {name}：{count}")
    lines.append("")

    lines.append("## 经验结论")
    lines.append("- 大多数合格日志都不是从百科背景起手，而是先抛判断、感受、问题或写作动机。")
    lines.append("- 合格样本普遍会在正文中形成‘判断 → 展开 → 例子 / 段落推进 → 回扣’的节奏，而不是一段写完就收。")
    lines.append("- 小标题不是必须，但当作者要同时处理主题、角色 / 结构 / 系统、个人余味时，小标题能明显改善可读性。")
    lines.append("- 站内成熟日志往往保留个人口吻，但不会一路碎碎念到底；它会在关键段落把判断压实。")
    lines.append("- 失败样本最常见的问题是：只剩剧情复述、只剩资料堆砌，或者只有情绪没有论证。")
    lines.append("")

    lines.append("## 代表样本")
    for row in reps:
        lines.append("")
        lines.append(f"### {row.get('title', '').strip()}")
        lines.append(f"- URL: {row.get('url', '')}")
        lines.append(f"- 作者: {row.get('author', '')}")
        lines.append(f"- 条目: {row.get('subject_title', '')}")
        lines.append(f"- 字数 / 段落: {row.get('char_count', 0)} / {row.get('paragraph_count', 0)}")
        lines.append(f"- 开头摘录: {row.get('opening_line', '')}")
        lines.append(f"- 结尾摘录: {row.get('closing_line', '')}")
        notes = row.get('structure_notes') or []
        if notes:
            lines.append(f"- 结构备注: {', '.join(notes)}")

    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=sorted(DOMAIN_LABELS))
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    samples_path = data_dir / "samples.jsonl"
    stats_path = data_dir / "stats.json"
    summary_path = data_dir / "summary.md"

    rows = load_jsonl(samples_path)
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    summary_path.write_text(build_markdown(args.domain, rows, stats), encoding="utf-8")
    print(str(summary_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
