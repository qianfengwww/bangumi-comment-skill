#!/usr/bin/env python3
from __future__ import annotations

import unittest
from argparse import Namespace
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect_book_materials import build_subject_selector, classify_urls, collect_book_bundle


class FakeClient:
    pass


def make_args(**overrides: object) -> Namespace:
    base = {
        "epub": [],
        "url": [],
        "subject_id": None,
        "subject_url": None,
        "title": None,
        "input": None,
        "output": None,
        "format": "json",
        "chapters": None,
        "epub_max_chars": 50000,
        "metadata_only": False,
        "extract_body": None,
        "web_max_chars": 50000,
        "cache_dir": ".cache/book-materials",
        "cache_ttl": 86400,
        "timeout": 30,
        "min_interval": 0.6,
    }
    base.update(overrides)
    return Namespace(**base)


class CollectBookMaterialsTests(unittest.TestCase):
    def test_classify_urls_splits_bangumi_subject_urls(self) -> None:
        bangumi_urls, web_urls = classify_urls(
            [
                "https://bgm.tv/subject/123",
                "https://example.com/review",
                "https://bangumi.tv/book/456",
            ]
        )
        self.assertEqual(
            bangumi_urls,
            ["https://bgm.tv/subject/123", "https://bangumi.tv/book/456"],
        )
        self.assertEqual(web_urls, ["https://example.com/review"])

    def test_build_subject_selector_uses_detected_bangumi_url(self) -> None:
        selector, warnings = build_subject_selector(
            make_args(url=["https://bgm.tv/subject/123"]),
            ["https://bgm.tv/subject/123"],
        )
        self.assertEqual(selector, {"subject_url": "https://bgm.tv/subject/123"})
        self.assertEqual(len(warnings), 1)

    def test_build_subject_selector_rejects_multiple_explicit_selectors(self) -> None:
        with self.assertRaises(ValueError):
            build_subject_selector(
                make_args(subject_id=1, title="三体"),
                [],
            )

    def test_collect_book_bundle_combines_subject_epub_and_web_materials(self) -> None:
        args = make_args(
            epub=["/tmp/test.epub"],
            url=["https://bgm.tv/subject/123", "https://example.com/review"],
        )

        with (
            patch(
                "collect_book_materials.collect_subject_material",
                return_value=(
                    {
                        "subject_id": 123,
                        "match_type": "url",
                        "query": "https://bgm.tv/subject/123",
                        "best_match": {"id": 123},
                    },
                    {
                        "subject": {
                            "subject_id": 123,
                            "title": "Book Original",
                            "title_cn": "书名",
                            "summary": "Bangumi summary",
                            "url": "https://bgm.tv/subject/123",
                            "tags": ["科幻"],
                        },
                        "material": {
                            "kind": "bangumi_subject",
                            "source": "https://bgm.tv/subject/123",
                            "title": "书名",
                            "content": "Bangumi summary",
                            "metadata": {"subject_id": 123},
                        },
                    },
                    0,
                ),
            ),
            patch(
                "collect_book_materials.collect_epub_material",
                return_value={
                    "kind": "epub",
                    "source": "/tmp/test.epub",
                    "title": "EPUB Title",
                    "content": "Chapter text",
                    "metadata": {"title": "EPUB Title", "author": "Author"},
                    "chapter_count": 10,
                    "selected_chapter_count": 10,
                    "chapters": [],
                },
            ),
            patch(
                "collect_book_materials.collect_web_materials",
                return_value=(
                    [
                        {
                            "kind": "web_page",
                            "source": "https://example.com/review",
                            "title": "Review",
                            "content": "Web text",
                            "metadata": {"mode": "extract", "truncated": False},
                        }
                    ],
                    [],
                ),
            ),
        ):
            bundle, exit_code = collect_book_bundle(args, client=FakeClient())

        self.assertEqual(exit_code, 0)
        self.assertEqual(bundle["subject"]["subject_id"], 123)
        self.assertEqual([item["kind"] for item in bundle["materials"]], ["bangumi_subject", "epub", "web_page"])
        self.assertEqual(len(bundle["warnings"]), 1)
        self.assertEqual(bundle["errors"], [])

    def test_collect_book_bundle_returns_partial_failure_when_subject_resolution_fails(self) -> None:
        args = make_args(
            epub=["/tmp/test.epub"],
            title="Unknown Book",
        )

        with (
            patch("collect_book_materials.collect_subject_material", side_effect=ValueError("未找到可用的 Bangumi 条目匹配")),
            patch(
                "collect_book_materials.collect_epub_material",
                return_value={
                    "kind": "epub",
                    "source": "/tmp/test.epub",
                    "title": "EPUB Title",
                    "content": "Chapter text",
                    "metadata": {"title": "EPUB Title"},
                    "chapter_count": 2,
                    "selected_chapter_count": 2,
                    "chapters": [],
                },
            ),
            patch("collect_book_materials.collect_web_materials", return_value=([], [])),
        ):
            bundle, exit_code = collect_book_bundle(args, client=FakeClient())

        self.assertEqual(exit_code, 1)
        self.assertIsNone(bundle["subject"])
        self.assertEqual(len(bundle["materials"]), 1)
        self.assertIn("Bangumi subject:", bundle["errors"][0])

    def test_collect_book_bundle_keeps_ambiguous_subject_candidate(self) -> None:
        args = make_args(title="三体")

        with (
            patch(
                "collect_book_materials.collect_subject_material",
                return_value=(
                    {
                        "subject_id": 123,
                        "match_type": "search",
                        "query": "三体",
                        "best_match": {"id": 123},
                        "alternatives": [{"id": 456}],
                        "error": {"code": "ambiguous_match", "message": "匹配结果存在歧义，请结合候选列表确认 subject_id"},
                    },
                    {
                        "subject": {
                            "subject_id": 123,
                            "title": "三体",
                            "title_cn": "三体",
                            "summary": "summary",
                            "url": "https://bgm.tv/subject/123",
                            "tags": [],
                        },
                        "material": {
                            "kind": "bangumi_subject",
                            "source": "https://bgm.tv/subject/123",
                            "title": "三体",
                            "content": "summary",
                            "metadata": {"subject_id": 123},
                        },
                    },
                    5,
                ),
            ),
            patch("collect_book_materials.collect_web_materials", return_value=([], [])),
        ):
            bundle, exit_code = collect_book_bundle(args, client=FakeClient())

        self.assertEqual(exit_code, 1)
        self.assertEqual(bundle["subject"]["subject_id"], 123)
        self.assertEqual(len(bundle["materials"]), 1)
        self.assertIn("Bangumi subject:", bundle["warnings"][0])


if __name__ == "__main__":
    unittest.main()
