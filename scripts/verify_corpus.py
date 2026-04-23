#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def verify_domain(path: Path, min_chars: int, min_paragraphs: int, min_count: int) -> dict:
    samples = load_jsonl(path / 'samples.jsonl')
    bad = []
    for row in samples:
        if row.get('char_count', 0) < min_chars or row.get('paragraph_count', 0) <= min_paragraphs:
            bad.append({
                'blog_id': row.get('blog_id'),
                'title': row.get('title'),
                'char_count': row.get('char_count'),
                'paragraph_count': row.get('paragraph_count'),
            })
    return {
        'count': len(samples),
        'ok_count': len(samples) >= min_count,
        'ok_thresholds': not bad,
        'bad_rows': bad[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--domains', nargs='+', default=['anime', 'book', 'game'])
    parser.add_argument('--min-chars', type=int, default=800)
    parser.add_argument('--min-paragraphs', type=int, default=3)
    parser.add_argument('--min-count-per-domain', type=int, default=100)
    parser.add_argument('--min-total', type=int, default=300)
    parser.add_argument('--max-total', type=int, default=500)
    args = parser.parse_args()

    root = Path(args.root)
    result = {'domains': {}, 'total_count': 0, 'ok_total_range': False}
    for domain in args.domains:
        info = verify_domain(root / domain, args.min_chars, args.min_paragraphs, args.min_count_per_domain)
        result['domains'][domain] = info
        result['total_count'] += info['count']

    result['ok_total_range'] = args.min_total <= result['total_count'] <= args.max_total
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['ok_total_range']:
        return 1
    for domain, info in result['domains'].items():
        if not info['ok_count'] or not info['ok_thresholds']:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
