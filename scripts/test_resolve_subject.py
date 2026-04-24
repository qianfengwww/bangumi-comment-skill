#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolve_subject import (
    extract_subject_id_from_url,
    is_ambiguous_match,
    normalize_title,
    rank_subjects,
    resolve_subject,
)


class FakeClient:
    def __init__(self, detail: dict | None = None, search_results: list[dict] | None = None) -> None:
        self.detail = detail or {}
        self.search_results = search_results or []

    def get_json(self, url: str, *, params: dict | None = None, **_: object) -> dict:
        if "/search/subjects" in url:
            return {"data": self.search_results}
        return self.detail


class ResolveSubjectTests(unittest.TestCase):
    def test_extract_subject_id_from_subject_url(self) -> None:
        self.assertEqual(extract_subject_id_from_url("https://bgm.tv/subject/51"), 51)
        self.assertEqual(extract_subject_id_from_url("https://bangumi.tv/subject/12345?from=search"), 12345)
        self.assertEqual(extract_subject_id_from_url("chii.in/game/9876"), 9876)

    def test_extract_subject_id_rejects_invalid_host(self) -> None:
        self.assertIsNone(extract_subject_id_from_url("https://example.com/subject/51"))
        self.assertIsNone(extract_subject_id_from_url("clannad"))

    def test_normalize_title(self) -> None:
        self.assertEqual(normalize_title("CLANNAD -クラナド-"), normalize_title("clannad クラナド"))
        self.assertEqual(normalize_title("Fate/stay night"), normalize_title("fate stay night"))

    def test_rank_subjects_prefers_exact_cn_match(self) -> None:
        ranked = rank_subjects(
            "CLANNAD",
            [
                {"id": 1, "name": "CLANNAD -クラナド-", "name_cn": "CLANNAD", "type": 2},
                {"id": 2, "name": "CLANNAD After Story", "name_cn": "团子大家族 第二季", "type": 2},
            ],
        )
        self.assertEqual(ranked[0]["id"], 1)
        self.assertTrue(ranked[0]["exact_match"])
        self.assertGreater(ranked[0]["match_score"], ranked[1]["match_score"])

    def test_ambiguous_match_detection(self) -> None:
        ranked = [
            {"id": 1, "match_score": 120.0, "exact_match": True},
            {"id": 2, "match_score": 119.0, "exact_match": True},
        ]
        self.assertTrue(is_ambiguous_match(ranked))

    def test_resolve_subject_accepts_subject_id(self) -> None:
        payload, exit_code = resolve_subject(
            FakeClient(detail={"id": 51, "name": "CLANNAD", "name_cn": "CLANNAD", "type": 2}),
            subject_id=51,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["subject_id"], 51)
        self.assertEqual(payload["match_type"], "subject_id")

    def test_resolve_subject_auto_detects_title_input(self) -> None:
        with patch(
            "resolve_subject.search_subjects",
            return_value=[{"id": 51, "name": "CLANNAD -クラナド-", "name_cn": "CLANNAD", "type": 2}],
        ):
            payload, exit_code = resolve_subject(
                FakeClient(),
                input_value="CLANNAD",
                domain="anime",
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["subject_id"], 51)
        self.assertEqual(payload["best_match"]["name_cn"], "CLANNAD")


if __name__ == "__main__":
    unittest.main()
