#!/usr/bin/env python3
"""
Convert repository-style Markdown drafts into Bangumi-friendly BBCode.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


HEADING_SIZES = {
    1: 7,
    2: 6,
    3: 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Markdown logs into Bangumi-friendly BBCode"
    )
    parser.add_argument("--input", "-i", help="Markdown input file path (defaults to stdin)")
    parser.add_argument("--output", "-o", help="BBCode output file path (defaults to stdout)")
    return parser


def protect_code_spans(text: str) -> tuple[str, list[str]]:
    code_spans: list[str] = []

    def repl(match: re.Match[str]) -> str:
        code_spans.append(f"[code]{match.group(1)}[/code]")
        return f"@@CODE{len(code_spans) - 1}@@"

    return re.sub(r"`([^`]+)`", repl, text), code_spans


def restore_code_spans(text: str, code_spans: list[str]) -> str:
    for index, replacement in enumerate(code_spans):
        text = text.replace(f"@@CODE{index}@@", replacement)
    return text


def convert_inline(text: str) -> str:
    protected, code_spans = protect_code_spans(text)
    protected = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"[url=\2]\1[/url]", protected)
    protected = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", protected)
    protected = re.sub(r"__(.+?)__", r"[b]\1[/b]", protected)
    protected = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"[i]\1[/i]", protected)
    protected = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"[i]\1[/i]", protected)
    return restore_code_spans(protected, code_spans)


def is_horizontal_rule(line: str) -> bool:
    stripped = line.strip()
    return stripped in {"---", "***", "___"}


def format_heading(level: int, text: str) -> str:
    label = convert_inline(text.strip())
    size = HEADING_SIZES.get(level)
    if size is None:
        return f"[b]{label}[/b]"
    return f"[size={size}][b]{label}[/b][/size]"


def convert_markdown(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            output.append("")
            index += 1
            continue

        if line.startswith("```"):
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            output.append("[code]")
            output.extend(code_lines)
            output.append("[/code]")
            if index < len(lines):
                index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            output.append(format_heading(len(heading_match.group(1)), heading_match.group(2)))
            output.append("")
            index += 1
            continue

        if is_horizontal_rule(line):
            output.append("[size=2]------------------------------[/size]")
            output.append("")
            index += 1
            continue

        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines):
                current = lines[index].strip()
                if not current.startswith(">"):
                    break
                quote_lines.append(convert_inline(current[1:].lstrip()))
                index += 1
            output.append("[quote]")
            output.extend(quote_lines)
            output.append("[/quote]")
            output.append("")
            continue

        unordered_match = re.match(r"^\s*[-*]\s+(.*)$", line)
        ordered_match = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if unordered_match or ordered_match:
            ordered = ordered_match is not None
            output.append("[list=1]" if ordered else "[list]")
            while index < len(lines):
                current_line = lines[index]
                current_match = (
                    re.match(r"^\s*\d+\.\s+(.*)$", current_line)
                    if ordered
                    else re.match(r"^\s*[-*]\s+(.*)$", current_line)
                )
                if not current_match:
                    break
                output.append(f"[*]{convert_inline(current_match.group(1).strip())}")
                index += 1
            output.append("[/list]")
            output.append("")
            continue

        output.append(convert_inline(line))
        index += 1

    return "\n".join(output).rstrip() + "\n"


def read_input(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def emit_output(text: str, path: str | None) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)


def main() -> int:
    args = build_parser().parse_args()
    markdown_text = read_input(args.input)
    bbcode_text = convert_markdown(markdown_text)
    emit_output(bbcode_text, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
