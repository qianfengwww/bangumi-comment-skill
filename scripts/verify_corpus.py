#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def parse_domains(values: list[str] | None) -> list[str]:
    if not values:
        return ["anime", "book", "game"]

    domains: list[str] = []
    for value in values:
        for part in value.split(","):
            item = part.strip()
            if item and item not in domains:
                domains.append(item)
    return domains


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    return None, f"{path}: 第 {line_no} 行 JSON 解析失败: {exc.msg}"
                if not isinstance(row, dict):
                    return None, f"{path}: 第 {line_no} 行不是 JSON 对象"
                rows.append(row)
    except FileNotFoundError:
        return None, f"{path}: 文件不存在"
    except OSError as exc:
        return None, f"{path}: 读取失败: {exc}"
    return rows, None


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须为非负整数")
    return parsed


def metric_int(row: dict[str, Any], key: str) -> int:
    value = row.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify corpus sample counts and thresholds")
    parser.add_argument("--root", default="data", help="Corpus root directory")
    parser.add_argument(
        "--domains",
        nargs="*",
        help="Domains to verify, supports space-separated or comma-separated values",
    )
    parser.add_argument("--min-chars", type=positive_int, default=800, help="Minimum char_count per sample")
    parser.add_argument("--min-paragraphs", type=positive_int, default=3, help="Minimum paragraph_count per sample")
    parser.add_argument("--min-count-per-domain", type=positive_int, default=1, help="Minimum accepted samples per domain")
    parser.add_argument("--min-total", type=positive_int, default=1, help="Minimum accepted samples across all domains")
    parser.add_argument("--max-total", type=positive_int, default=0, help="Maximum accepted samples across all domains, 0 means unlimited")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    domains = parse_domains(args.domains)
    root = Path(args.root)

    errors: list[str] = []
    domain_results: list[dict[str, Any]] = []
    total_accepted = 0

    if not domains:
        errors.append("未指定任何 domains")

    if not root.exists():
        errors.append(f"{root}: 根目录不存在")
    elif not root.is_dir():
        errors.append(f"{root}: 根路径不是目录")

    if args.max_total and args.max_total < args.min_total:
        errors.append("max-total 不能小于 min-total")

    if errors:
        print(
            json_result(
                {
                    "ok": False,
                    "root": str(root),
                    "domains": domains,
                    "errors": errors,
                    "results": [],
                }
            ),
            end="",
        )
        return 1

    for domain in domains:
        samples_path = root / domain / "samples.jsonl"
        rows, error = load_jsonl(samples_path)
        if error:
            errors.append(error)
            continue

        assert rows is not None
        accepted = 0
        rejected = 0
        invalid_examples: list[dict[str, Any]] = []

        for index, row in enumerate(rows, start=1):
            char_count = metric_int(row, "char_count")
            paragraph_count = metric_int(row, "paragraph_count")
            reasons: list[str] = []
            if char_count < args.min_chars:
                reasons.append(f"char_count<{args.min_chars}")
            if paragraph_count < args.min_paragraphs:
                reasons.append(f"paragraph_count<{args.min_paragraphs}")

            if reasons:
                rejected += 1
                if len(invalid_examples) < 5:
                    invalid_examples.append(
                        {
                            "line": index,
                            "title": row.get("title", ""),
                            "url": row.get("url", ""),
                            "char_count": char_count,
                            "paragraph_count": paragraph_count,
                            "reasons": reasons,
                        }
                    )
                continue

            accepted += 1

        total_accepted += accepted

        domain_errors: list[str] = []
        if accepted < args.min_count_per_domain:
            domain_errors.append(
                f"accepted={accepted} 小于 min-count-per-domain={args.min_count_per_domain}"
            )

        domain_results.append(
            {
                "domain": domain,
                "samples_path": str(samples_path),
                "total_rows": len(rows),
                "accepted": accepted,
                "rejected": rejected,
                "min_chars": args.min_chars,
                "min_paragraphs": args.min_paragraphs,
                "ok": not domain_errors,
                "errors": domain_errors,
                "invalid_examples": invalid_examples,
            }
        )
        errors.extend(f"{domain}: {message}" for message in domain_errors)

    if not errors:
        if total_accepted < args.min_total:
            errors.append(f"accepted_total={total_accepted} 小于 min-total={args.min_total}")
        if args.max_total and total_accepted > args.max_total:
            errors.append(f"accepted_total={total_accepted} 大于 max-total={args.max_total}")

    payload = {
        "ok": not errors,
        "root": str(root),
        "domains": domains,
        "thresholds": {
            "min_chars": args.min_chars,
            "min_paragraphs": args.min_paragraphs,
            "min_count_per_domain": args.min_count_per_domain,
            "min_total": args.min_total,
            "max_total": args.max_total,
        },
        "summary": {
            "domains_checked": len(domains),
            "domains_loaded": len(domain_results),
            "accepted_total": total_accepted,
        },
        "results": domain_results,
        "errors": errors,
    }
    print(json_result(payload), end="")

    if any("文件不存在" in error or "JSON 解析失败" in error or "读取失败" in error or "不是 JSON 对象" in error for error in errors):
        return 1
    if errors:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
