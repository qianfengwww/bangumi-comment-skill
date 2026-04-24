#!/usr/bin/env python3
from __future__ import annotations

import unittest
from argparse import Namespace
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect_materials import build_subject_selector, classify_urls, collect_bundle


class FakeClient:
    pass


def make_args(**overrides: object) -> Namespace:
    base = {
        "domain": "anime",
        "subject_id": None,
        "subject_url": None,
        "title": None,
        "input": None,
        "url": [],
        "epub": [],
        "output": None,
        "format": "json",
        "include_bangumi_logs": False,
        "include_comments": False,
        "log_limit": 8,
        "log_min_length": 150,
        "fetch_web_detail": False,
        "include_guidance": False,
        "chapters": None,
        "metadata_only": False,
        "epub_max_chars": 50000,
        "extract_body": None,
        "web_max_chars": 50000,
        "cache_dir": ".cache/materials",
        "cache_ttl": 86400,
        "timeout": 30,
        "min_interval": 0.8,
    }
    base.update(overrides)
    return Namespace(**base)


class CollectMaterialsTests(unittest.TestCase):
    def test_classify_urls_splits_bangumi_subject_urls(self) -> None:
        bangumi_urls, generic_urls = classify_urls(
            [
                "https://bgm.tv/subject/123",
                "https://example.com/wiki",
                "https://bangumi.tv/game/456",
            ]
        )
        self.assertEqual(bangumi_urls, ["https://bgm.tv/subject/123", "https://bangumi.tv/game/456"])
        self.assertEqual(generic_urls, ["https://example.com/wiki"])

    def test_build_subject_selector_prefers_detected_bangumi_url(self) -> None:
        selector, warnings = build_subject_selector(
            subject_id=None,
            subject_url=None,
            title=None,
            input_value=None,
            bangumi_subject_urls=["https://bgm.tv/subject/123"],
        )
        self.assertEqual(selector, {"subject_url": "https://bgm.tv/subject/123"})
        self.assertEqual(len(warnings), 1)

    def test_build_subject_selector_rejects_multiple_explicit_selectors(self) -> None:
        with self.assertRaises(ValueError):
            build_subject_selector(
                subject_id=1,
                subject_url=None,
                title="CLANNAD",
                input_value=None,
                bangumi_subject_urls=[],
            )

    def test_collect_bundle_normalizes_anime_subject_web_and_logs(self) -> None:
        args = make_args(
            domain="anime",
            title="CLANNAD",
            url=["https://example.com/wiki"],
            include_bangumi_logs=True,
        )

        with (
            patch("collect_materials.build_client", return_value=FakeClient()),
            patch(
                "collect_materials.collect_anime_bundle",
                return_value=(
                    {
                        "subject_id": 51,
                        "title": "CLANNAD -クラナド-",
                        "title_cn": "CLANNAD",
                        "url": "https://bgm.tv/subject/51",
                        "summary": "summary",
                    },
                    {
                        "subject_id": 51,
                        "match_type": "search",
                        "query": "CLANNAD",
                        "best_match": {"id": 51},
                    },
                    [
                        {
                            "kind": "bangumi_subject",
                            "domain": "anime",
                            "source": "https://bgm.tv/subject/51",
                            "title": "CLANNAD",
                            "content": "summary",
                            "metadata": {"subject_id": 51},
                        },
                        {
                            "kind": "anime_episodes",
                            "domain": "anime",
                            "source": "https://bgm.tv/subject/51",
                            "title": "CLANNAD",
                            "content": "episodes",
                            "metadata": {"subject_id": 51, "episode_count": 24},
                            "episodes": [],
                        },
                    ],
                    [],
                    [],
                    0,
                ),
            ),
            patch(
                "collect_materials.collect_web_materials",
                return_value=(
                    [
                        {
                            "kind": "web_page",
                            "domain": "anime",
                            "source": "https://example.com/wiki",
                            "title": "Wiki",
                            "content": "web text",
                            "metadata": {"mode": "extract"},
                        }
                    ],
                    [],
                ),
            ),
            patch(
                "collect_materials.collect_bangumi_logs_material",
                return_value=(
                    {
                        "kind": "bangumi_logs",
                        "domain": "anime",
                        "source": "https://bgm.tv/subject/51/reviews",
                        "title": "CLANNAD Bangumi logs",
                        "content": "log text",
                        "metadata": {"subject_id": 51, "count": 2},
                        "entries": [],
                    },
                    [],
                    0,
                ),
            ),
        ):
            bundle, exit_code = collect_bundle(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(bundle["subject"]["subject_id"], 51)
        self.assertEqual(bundle["subject_resolution"]["subject_id"], 51)
        self.assertEqual(
            [item["kind"] for item in bundle["materials"]],
            ["bangumi_subject", "anime_episodes", "web_page", "bangumi_logs"],
        )

    def test_collect_bundle_uses_book_collector_and_preserves_resolution(self) -> None:
        args = make_args(
            domain="book",
            title="三体",
            epub=["/tmp/book.epub"],
        )

        with (
            patch("collect_materials.build_client", return_value=FakeClient()),
            patch(
                "collect_materials.collect_book_domain_bundle",
                return_value=(
                    {
                        "subject_id": 9585,
                        "title": "三体",
                        "title_cn": "三体",
                        "summary": "summary",
                        "url": "https://bgm.tv/subject/9585",
                    },
                    [
                        {
                            "kind": "bangumi_subject",
                            "domain": "book",
                            "source": "https://bgm.tv/subject/9585",
                            "title": "三体",
                            "content": "summary",
                            "metadata": {"subject_id": 9585},
                        },
                        {
                            "kind": "epub",
                            "domain": "book",
                            "source": "/tmp/book.epub",
                            "title": "三体",
                            "content": "chapter text",
                            "metadata": {"title": "三体"},
                        },
                    ],
                    [],
                    [],
                    {"subject_id": 9585, "match_type": "search"},
                    0,
                ),
            ),
        ):
            bundle, exit_code = collect_bundle(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(bundle["subject_resolution"]["subject_id"], 9585)
        self.assertEqual([item["kind"] for item in bundle["materials"]], ["bangumi_subject", "epub"])

    def test_collect_bundle_rejects_epub_for_non_book(self) -> None:
        with self.assertRaises(ValueError):
            collect_bundle(make_args(domain="anime", epub=["/tmp/book.epub"]))


if __name__ == "__main__":
    unittest.main()
