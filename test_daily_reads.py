import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest import mock


def install_test_stubs():
    google = ModuleType("google")
    google_auth = ModuleType("google.auth")
    google_auth_transport = ModuleType("google.auth.transport")
    google_auth_transport_requests = ModuleType("google.auth.transport.requests")
    google_auth_transport_requests.Request = object
    google_oauth2 = ModuleType("google.oauth2")
    google_oauth2_credentials = ModuleType("google.oauth2.credentials")

    class DummyCredentials:
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_info(cls, token_data):
            return cls()

        def refresh(self, request):
            return None

    google_oauth2_credentials.Credentials = DummyCredentials

    googleapiclient = ModuleType("googleapiclient")
    googleapiclient_discovery = ModuleType("googleapiclient.discovery")
    googleapiclient_discovery.build = lambda *args, **kwargs: None

    bs4 = ModuleType("bs4")

    class DummySoup:
        def __init__(self, html, parser):
            self.html = html

        def find_all(self, *args, **kwargs):
            return []

    bs4.BeautifulSoup = DummySoup

    sys.modules.setdefault("google", google)
    sys.modules.setdefault("google.auth", google_auth)
    sys.modules.setdefault("google.auth.transport", google_auth_transport)
    sys.modules.setdefault("google.auth.transport.requests", google_auth_transport_requests)
    sys.modules.setdefault("google.oauth2", google_oauth2)
    sys.modules.setdefault("google.oauth2.credentials", google_oauth2_credentials)
    sys.modules.setdefault("googleapiclient", googleapiclient)
    sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery)
    sys.modules.setdefault("bs4", bs4)
    sys.modules.setdefault("anthropic", SimpleNamespace(Anthropic=object))


install_test_stubs()

import gmail_reader
import main
import analyze_history
import preference_learning
import process_criteria_feedback
import process_dropbox_exemplars
import process_exemplar_content
import process_email_exemplars
import process_email_feedback
import process_readwise_exemplars
import project_data
import readwise_client


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 4, 1, 12, 0, 0, tzinfo=tz or timezone.utc)


class DailyReadsTests(unittest.TestCase):
    def run_criteria_feedback_processor(self, issue):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            original_token = os.environ.get("GITHUB_TOKEN")
            try:
                os.chdir(tmpdir)
                os.environ["GITHUB_TOKEN"] = "test-token"
                with open("criteria_update_state.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "pending": {
                                "proposal_id": "2026-03-28-r1",
                                "status": "pending",
                                "revision": 1,
                                "summary": ["example"],
                                "diff_lines": ["Added: example"],
                            },
                            "history": [],
                        },
                        f,
                    )
                with open("selection_criteria.md", "w", encoding="utf-8") as f:
                    f.write("# Current\nold\n")
                with open("selection_criteria_proposed.md", "w", encoding="utf-8") as f:
                    f.write("# Proposed\nnew\n")

                mock_get_response = mock.Mock()
                mock_get_response.raise_for_status.return_value = None
                mock_get_response.json.return_value = [issue]

                with mock.patch.object(process_criteria_feedback.requests, "get", return_value=mock_get_response), \
                     mock.patch.object(process_criteria_feedback.requests, "patch", return_value=mock.Mock()), \
                     mock.patch.object(process_criteria_feedback, "commit_durable_state", return_value=True):
                    process_criteria_feedback.main()

                with open("criteria_update_state.json", "r", encoding="utf-8") as f:
                    state = json.load(f)
                with open("selection_criteria.md", "r", encoding="utf-8") as f:
                    current = f.read()
                return state, current
            finally:
                os.chdir(original_cwd)
                if original_token is None:
                    os.environ.pop("GITHUB_TOKEN", None)
                else:
                    os.environ["GITHUB_TOKEN"] = original_token

    def test_validate_selected_articles_rejects_duplicate_slot_and_source(self):
        articles = [
            {
                "headline": "A",
                "source": "BioSpace",
                "url": "https://example.com/a",
                "slot": 1,
                "summary": "Summary A",
                "why_it_matters": "Why A",
                "signal_tags": ["tag:a"],
            },
            {
                "headline": "B",
                "source": "BioSpace",
                "url": "https://example.com/b",
                "slot": 1,
                "summary": "Summary B",
                "why_it_matters": "Why B",
                "signal_tags": ["tag:b"],
            },
            {
                "headline": "C",
                "source": "WSJ",
                "url": "https://example.com/c",
                "slot": 2,
                "summary": "Summary C",
                "why_it_matters": "Why C",
                "signal_tags": ["tag:c"],
            },
            {
                "headline": "D",
                "source": "HN",
                "url": "https://example.com/d",
                "slot": 3,
                "summary": "Summary D",
                "why_it_matters": "Why D",
                "signal_tags": ["tag:d"],
            },
        ]

        validated = main.validate_selected_articles(articles)

        self.assertEqual([article["slot"] for article in validated], [1, 2, 3])
        self.assertEqual([article["source"] for article in validated], ["BioSpace", "WSJ", "HN"])

    def test_feedback_check_handles_month_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with open("feedback_log.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {"date": "2026-03-31", "slot": 1, "score": 1, "note": "miss"},
                            {"date": "2026-03-30", "slot": 2, "score": 3, "note": "old"},
                        ],
                        f,
                    )

                with mock.patch.object(main, "datetime", FixedDateTime):
                    result = main.feedback_check()
            finally:
                os.chdir(original_cwd)

        self.assertTrue(result["low_scores"])
        self.assertEqual(result["low_scores"][0]["date"], "2026-03-31")

    def test_email_feedback_parser_supports_three_point_scale(self):
        matches = list(process_email_feedback.FEEDBACK_RE.finditer("1 3\n2 okay\n3 1 too generic"))

        self.assertEqual(len(matches), 3)
        parsed = [
            (
                int(match.group(1)),
                process_email_feedback.SCORE_MAP[match.group(2).lower()],
                (match.group(3) or "").strip(),
            )
            for match in matches
        ]
        self.assertEqual(
            parsed,
            [
                (1, 3, ""),
                (2, 2, ""),
                (3, 1, "too generic"),
            ],
        )

    def test_slack_mailto_feedback_url_prefills_email(self):
        url = main.slack_mailto_feedback_url("2026-03-28", 2, 3)

        self.assertIn("mailto:jroypeterson@gmail.com", url)
        self.assertIn("subject=Daily+Reads+feedback+2026-03-28", url)
        self.assertIn("body=2+3", url)

    def test_criteria_issue_url_uses_issue_flow(self):
        url = main.criteria_issue_url("modify", "2026-03-28-r1")

        self.assertIn("/issues/new?", url)
        self.assertIn("labels=criteria-update", url)
        self.assertIn("Criteria+Update%3A+modify+2026-03-28-r1", url)

    def test_build_criteria_diff_lines_summarizes_added_and_removed_lines(self):
        current = "# Criteria\n- Prefer finance\n- Avoid generic AI\n"
        proposed = "# Criteria\n- Prefer biotech catalysts\n- Avoid generic AI\n- Add long-form strategy\n"

        diff_lines = main.build_criteria_diff_lines(current, proposed)

        self.assertIn("Removed: - Prefer finance", diff_lines)
        self.assertIn("Added: - Prefer biotech catalysts", diff_lines)
        self.assertIn("Added: - Add long-form strategy", diff_lines)

    def test_article_id_is_stable_for_normalized_url(self):
        left = project_data.article_id_for("https://Example.com/path/", "BioSpace")
        right = project_data.article_id_for("https://example.com/path", "biospace")

        self.assertEqual(left, right)

    def test_enrich_feedback_entry_uses_run_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                os.makedirs("artifacts/runs", exist_ok=True)
                with open("artifacts/runs/2026-03-28.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "articles": [
                                {
                                    "slot": 2,
                                    "article_id": "abc123",
                                    "headline": "Markets setup",
                                    "url": "https://example.com/markets",
                                    "source": "Example Finance",
                                }
                            ]
                        },
                        f,
                    )

                entry = project_data.enrich_feedback_entry("2026-03-28", 2, "email_reply", 3, "good one")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(entry["article_id"], "abc123")
        self.assertEqual(entry["headline"], "Markets setup")
        self.assertEqual(entry["article_source"], "Example Finance")
        self.assertEqual(entry["channel"], "email_reply")

    def test_candidate_artifact_path(self):
        path = project_data.candidate_artifact_path("2026-03-28")

        self.assertEqual(path, os.path.join("artifacts", "candidates", "2026-03-28.json"))

    def test_normalize_candidate_preserves_source_metadata(self):
        candidate = main.normalize_candidate(
            {
                "source_name": "BioSpace",
                "subject": "Catalyst headline",
                "snippet": "Snippet",
                "urls": ["https://example.com/path/"],
                "category": "healthcare_daily",
                "priority": "high",
                "tier": 1,
                "sender_email": "newsletters@biospace.com",
                "sender": "BioSpace <newsletters@biospace.com>",
                "date": "Fri, 28 Mar 2026 07:00:00 +0000",
            },
            "gmail",
            "2026-03-28",
            1,
        )

        self.assertEqual(candidate["source_type"], "gmail")
        self.assertEqual(candidate["headline"], "Catalyst headline")
        self.assertEqual(candidate["primary_url"], "https://example.com/path/")
        self.assertEqual(candidate["category"], "healthcare_daily")
        self.assertEqual(candidate["sender_email"], "newsletters@biospace.com")

    def test_extract_candidate_signals_includes_priority_and_ticker(self):
        signals = main.extract_candidate_signals(
            {
                "headline": "ABBV catalyst update",
                "snippet": "Biotech readout",
                "source_name": "BioSpace",
                "category": "healthcare_daily",
                "priority": "high",
                "source_type": "gmail",
                "score": None,
            },
            {"ABBV", "MRNA"},
        )

        self.assertIn("priority:high", signals)
        self.assertIn("source_type:gmail", signals)
        self.assertIn("category:healthcare_daily", signals)
        self.assertIn("ticker:ABBV", signals)

    def test_build_structured_candidates_adds_derived_signals(self):
        gmail, tier2 = main.build_structured_candidates(
            [
                {
                    "source_name": "BioSpace",
                    "subject": "ABBV catalyst update",
                    "snippet": "Biotech readout",
                    "urls": ["https://example.com/biotech"],
                    "category": "healthcare_daily",
                    "priority": "high",
                    "tier": 1,
                }
            ],
            [
                {
                    "source_name": "Hacker News",
                    "subject": "AI infra story",
                    "snippet": "GPU demand",
                    "urls": ["https://example.com/ai"],
                    "category": "tech_ai",
                    "priority": "normal",
                    "tier": 2,
                    "score": 120,
                }
            ],
            "2026-03-28",
            {"healthcare": ["ABBV"], "tech": ["NVDA"], "other": []},
        )

        self.assertEqual(len(gmail), 1)
        self.assertEqual(len(tier2), 1)
        self.assertIn("ticker:ABBV", gmail[0]["derived_signals"])
        self.assertIn("hn_score:120", tier2[0]["derived_signals"])

    def test_build_triage_queue_ranks_unselected_candidates(self):
        triage = main.build_triage_queue(
            [
                {
                    "candidate_id": "c1",
                    "headline": "High priority biotech",
                    "source_name": "BioSpace",
                    "source_type": "gmail",
                    "priority": "high",
                    "tier": 1,
                    "primary_url": "https://example.com/biotech",
                    "derived_signals": ["ticker:ABBV", "priority:high"],
                }
            ],
            [
                {
                    "candidate_id": "c2",
                    "headline": "HN AI story",
                    "source_name": "Hacker News",
                    "source_type": "tier2",
                    "priority": "normal",
                    "tier": 2,
                    "score": 150,
                    "primary_url": "https://example.com/ai",
                    "derived_signals": ["hn_score:150"],
                }
            ],
            [{"url": "https://example.com/ai"}],
        )

        self.assertEqual(len(triage), 1)
        self.assertEqual(triage[0]["candidate_id"], "c1")
        self.assertGreater(triage[0]["triage_score"], 0)

    def test_clean_url_strips_tracking_params(self):
        cleaned = gmail_reader.clean_url(
            "https://example.com/article/?utm_source=newsletter&gclid=abc&id=42#section"
        )

        self.assertEqual(cleaned, "https://example.com/article?id=42")

    def test_is_probable_article_url_rejects_non_article_paths(self):
        self.assertFalse(gmail_reader.is_probable_article_url("https://example.com/account/settings"))
        self.assertFalse(gmail_reader.is_probable_article_url("https://example.com/"))
        self.assertTrue(gmail_reader.is_probable_article_url("https://example.com/news/fda-decision"))

    def test_render_preferences_markdown_includes_evidence(self):
        markdown = preference_learning.render_preferences_markdown(
            {
                "version": 2,
                "updated_at": "2026-03-28T12:00:00Z",
                "evidence_summary": {
                    "total": 5,
                    "by_kind": {"positive_exemplar": 3, "daily_rating_3": 2},
                    "by_channel": {"dropbox": 2, "daily_scoring": 2, "email": 1},
                },
                "topic_preferences": [
                    {"name": "biotech catalysts", "strength": "strong", "direction": "positive", "evidence_ids": ["ev_1", "ev_2"]}
                ],
                "source_preferences": [],
                "style_preferences": [],
                "avoid_patterns": [
                    {"name": "generic roundups", "strength": "moderate", "direction": "negative", "evidence_ids": ["ev_3"]}
                ],
            }
        )

        self.assertIn("Total evidence records: 5", markdown)
        self.assertIn("biotech catalysts", markdown)
        self.assertIn("generic roundups", markdown)
        self.assertIn("strong", markdown)

    def test_email_exemplar_query_uses_alias_and_label(self):
        query = process_email_exemplars.message_query(24)

        self.assertIn("to:jroypeterson+taste@gmail.com", query)
        self.assertIn("label:taste", query)

    def test_email_exemplar_url_extraction_filters_tracking_links(self):
        urls = process_email_exemplars.extract_candidate_urls(
            "Read this https://example.com/article/?utm_source=news&id=42 and skip https://example.com/account/settings"
        )

        self.assertEqual(urls, ["https://example.com/article?id=42"])

    def test_dropbox_exemplar_builds_url_record_from_text_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "taste")
            os.makedirs(root, exist_ok=True)
            path = os.path.join(root, "idea.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("https://example.com/report?utm_source=inbox\n\nGood structure")
            with open(path + ".note.txt", "w", encoding="utf-8") as f:
                f.write("Investor-style framing")

            exemplar = process_dropbox_exemplars.build_exemplar(
                process_dropbox_exemplars.Path(path),
                process_dropbox_exemplars.Path(root),
            )

        self.assertEqual(exemplar["kind"], "positive_exemplar")
        self.assertEqual(exemplar["url"], "https://example.com/report")
        self.assertEqual(exemplar["note"], "Investor-style framing")

    def test_dropbox_exemplar_uses_default_directory(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            root = process_dropbox_exemplars.configured_dropbox_dir()

        self.assertEqual(
            str(root),
            r"C:\Users\jroyp\Dropbox\Claude Folder\daily-reads-taste-samples",
        )

    def test_archive_processed_file_moves_source_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = process_dropbox_exemplars.Path(tmpdir)
            source = root / "sample.pdf"
            source.write_bytes(b"pdf")
            note = root / "sample.pdf.note.txt"
            note.write_text("good one", encoding="utf-8")

            moved = process_dropbox_exemplars.archive_processed_file(source, root)

            archive_root = root / "Incorporated into taste preferences"
            self.assertTrue(moved.exists())
            self.assertTrue((archive_root / "sample.pdf.note.txt").exists())
            self.assertFalse(source.exists())
            self.assertFalse(note.exists())

    def test_fast_update_preferences_counts_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with open("taste_evidence.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": "ev_001",
                                "kind": "positive_exemplar",
                                "source_channel": "dropbox",
                                "title": "Dropbox exemplar",
                                "url": "https://example.com/b",
                                "note": "Useful framing",
                                "score": None,
                                "content_status": "extracted",
                                "metadata": {"extracted_text_preview": "Biotech market structure and capital cycles"},
                                "created_at": "2026-03-28T10:00:00Z",
                                "local_path": "",
                            },
                            {
                                "id": "ev_002",
                                "kind": "daily_rating_3",
                                "source_channel": "daily_scoring",
                                "title": "Strong pick article",
                                "url": "https://example.com/c",
                                "note": "",
                                "score": 3,
                                "content_status": "not_applicable",
                                "metadata": {},
                                "created_at": "2026-03-28T12:00:00Z",
                                "local_path": "",
                            },
                        ],
                        f,
                    )

                preferences = preference_learning.fast_update_preferences()
            finally:
                os.chdir(original_cwd)

        self.assertEqual(preferences["version"], 2)
        self.assertEqual(preferences["evidence_summary"]["total"], 2)
        self.assertEqual(preferences["evidence_summary"]["by_kind"]["positive_exemplar"], 1)
        self.assertEqual(preferences["evidence_summary"]["by_kind"]["daily_rating_3"], 1)

    def test_load_learned_preferences_summary_v2_structured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with open("learned_preferences.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "version": 2,
                            "topic_preferences": [
                                {"name": "biotech catalysts", "strength": "strong", "direction": "positive", "evidence_ids": ["ev_1", "ev_2"]}
                            ],
                            "source_preferences": [],
                            "style_preferences": [],
                            "avoid_patterns": [
                                {"name": "generic roundups", "strength": "moderate", "direction": "negative", "evidence_ids": ["ev_3"]}
                            ],
                            "evidence_summary": {"total": 3, "by_kind": {}, "by_channel": {}},
                        },
                        f,
                    )
                with open("taste_evidence.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": "ev_1",
                                "kind": "positive_exemplar",
                                "source_channel": "dropbox",
                                "title": "Industry structure report",
                                "note": "Excellent market map",
                                "url": "",
                                "local_path": "",
                                "score": None,
                                "content_status": "extracted",
                                "metadata": {},
                                "created_at": "2026-03-28T10:00:00Z",
                            }
                        ],
                        f,
                    )
                summary = main.load_learned_preferences_summary()
            finally:
                os.chdir(original_cwd)

        self.assertIn("biotech catalysts", summary)
        self.assertIn("STRONG", summary)
        self.assertIn("AVOID", summary)
        self.assertIn("generic roundups", summary)
        self.assertIn("Industry structure report", summary)

    def test_process_exemplar_content_extracts_text_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                sample_path = os.path.join(tmpdir, "sample.txt")
                with open(sample_path, "w", encoding="utf-8") as f:
                    f.write("This is a detailed market structure memo with useful specificity.")
                with open("taste_evidence.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": "ev_test1",
                                "kind": "positive_exemplar",
                                "local_path": sample_path,
                                "content_status": "local_file_pending",
                                "metadata": {},
                            }
                        ],
                        f,
                    )

                process_exemplar_content.main()

                with open("taste_evidence.json", "r", encoding="utf-8") as f:
                    exemplars = json.load(f)
            finally:
                os.chdir(original_cwd)

        self.assertEqual(exemplars[0]["content_status"], "extracted")
        self.assertIn("market structure memo", exemplars[0]["metadata"]["extracted_text_preview"])

    def test_analyze_history_handles_empty_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with open("feedback_log.json", "w", encoding="utf-8") as f:
                    json.dump([], f)
                with open("learned_preferences.json", "w", encoding="utf-8") as f:
                    json.dump({"version": 2, "updated_at": "never", "evidence_summary": {"total": 0, "by_kind": {}, "by_channel": {}}, "topic_preferences": [], "avoid_patterns": []}, f)
                with open("criteria_update_state.json", "w", encoding="utf-8") as f:
                    json.dump({"pending": None, "history": []}, f)

                report = analyze_history.build_report()
            finally:
                os.chdir(original_cwd)

        self.assertIn("Run artifacts: 0", report)
        self.assertIn("Candidate artifacts: 0", report)
        self.assertIn("Feedback entries: 0", report)

    def test_analyze_history_summarizes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                os.makedirs("artifacts/runs", exist_ok=True)
                os.makedirs("artifacts/candidates", exist_ok=True)
                with open("artifacts/runs/2026-03-28.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "run_date": "2026-03-28",
                            "articles": [
                                {"slot": 1, "source": "BioSpace"},
                                {"slot": 3, "source": "Example Tech"},
                            ],
                        },
                        f,
                    )
                with open("artifacts/candidates/2026-03-28.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "gmail_candidates": [{"category": "healthcare_daily"}],
                            "tier2_candidates": [{"category": "tech_ai"}, {"category": "tech_ai"}],
                        },
                        f,
                    )
                os.makedirs("artifacts/triage", exist_ok=True)
                with open("artifacts/triage/2026-03-28.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "triage_queue": [
                                {"source_name": "BioSpace"},
                                {"source_name": "Example Tech"},
                            ]
                        },
                        f,
                    )
                with open("feedback_log.json", "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {"score": 3, "channel": "email_reply", "article_id": "abc", "slot": 1, "article_source": "BioSpace"},
                            {"score": 1, "channel": "github_issue", "slot": 1, "article_source": "BioSpace", "note": "too generic"},
                            {"score": 2, "channel": "email_reply", "slot": 3, "article_source": "Example Tech"},
                        ],
                        f,
                    )
                with open("learned_preferences.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "version": 2,
                            "updated_at": "2026-03-28T12:00:00Z",
                            "evidence_summary": {
                                "total": 5,
                                "by_kind": {"positive_exemplar": 3, "daily_rating_3": 1, "daily_rating_1": 1},
                                "by_channel": {"dropbox": 2, "daily_scoring": 2, "email": 1},
                            },
                            "topic_preferences": [{"name": "biotech", "strength": "moderate", "direction": "positive", "evidence_ids": ["ev_1"]}],
                            "avoid_patterns": [],
                        },
                        f,
                    )
                with open("criteria_update_state.json", "w", encoding="utf-8") as f:
                    json.dump({"pending": {"proposal_id": "2026-03-28-r1"}, "history": [{}]}, f)

                report = analyze_history.build_report()
            finally:
                os.chdir(original_cwd)

        self.assertIn("Run artifacts: 1", report)
        self.assertIn("Selected articles across runs: 2", report)
        self.assertIn("Total candidates seen: 3", report)
        self.assertIn("Triage artifacts: 1", report)
        self.assertIn("Entries linked to article IDs: 1", report)
        self.assertIn("Selection rate: 0.667", report)
        self.assertIn("1: 2.0", report)
        self.assertIn("BioSpace: 2.0", report)
        self.assertIn("too generic: 1", report)
        self.assertIn("Pending proposal: 2026-03-28-r1", report)
        self.assertIn("Total evidence records: 5", report)
        self.assertIn("Learned topic preferences: 1", report)

    def test_criteria_feedback_accept_applies_proposal(self):
        state, current = self.run_criteria_feedback_processor(
            {
                "number": 1,
                "title": "Criteria Update: accept 2026-03-28-r1",
                "body": "Proposal ID: 2026-03-28-r1\n\nAction: accept\n",
            }
        )

        self.assertIsNone(state["pending"])
        self.assertEqual(state["history"][0]["resolution"], "accepted")
        self.assertEqual(current, "# Proposed\nnew\n")

    def test_criteria_feedback_reject_clears_pending(self):
        state, current = self.run_criteria_feedback_processor(
            {
                "number": 2,
                "title": "Criteria Update: reject 2026-03-28-r1",
                "body": "Proposal ID: 2026-03-28-r1\n\nAction: reject\n",
            }
        )

        self.assertIsNone(state["pending"])
        self.assertEqual(state["history"][0]["resolution"], "rejected")
        self.assertEqual(current, "# Current\nold\n")

    def test_criteria_feedback_modify_stores_note(self):
        state, current = self.run_criteria_feedback_processor(
            {
                "number": 3,
                "title": "Criteria Update: modify 2026-03-28-r1",
                "body": "Proposal ID: 2026-03-28-r1\n\nRequested changes:\nTighten biotech emphasis\n",
            }
        )

        self.assertEqual(state["pending"]["status"], "modification_requested")
        self.assertEqual(state["pending"]["modification_note"], "Tighten biotech emphasis")
        self.assertEqual(current, "# Current\nold\n")

    # -- Readwise Reader push -------------------------------------------------

    def test_deliver_reader_skips_without_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(main.requests, "post") as post:
                main.deliver_reader(
                    [{"url": "https://example.com/a", "headline": "A"}],
                    [{"primary_url": "https://example.com/b", "headline": "B"}],
                )
        post.assert_not_called()

    def test_deliver_reader_pushes_top_picks_and_always_read(self):
        resp = mock.Mock(status_code=201, headers={}, text="")
        with mock.patch.dict(os.environ, {"READWISE_TOKEN": "tok123"}, clear=True):
            with mock.patch.object(main.requests, "post", return_value=resp) as post:
                main.deliver_reader(
                    [{"url": "https://example.com/top", "headline": "Top Pick", "summary": "why"}],
                    [{"primary_url": "https://example.com/always", "subject": "Always Item"}],
                )

        self.assertEqual(post.call_count, 2)
        first = post.call_args_list[0]
        self.assertEqual(first.args[0], "https://readwise.io/api/v3/save/")
        self.assertEqual(first.kwargs["headers"]["Authorization"], "Token tok123")
        top_body = first.kwargs["json"]
        self.assertEqual(top_body["url"], "https://example.com/top")
        self.assertEqual(top_body["title"], "Top Pick")
        self.assertEqual(top_body["location"], "later")
        self.assertIn("top-pick", top_body["tags"])
        self.assertEqual(top_body["summary"], "why")

        always_body = post.call_args_list[1].kwargs["json"]
        self.assertEqual(always_body["url"], "https://example.com/always")
        self.assertEqual(always_body["title"], "Always Item")  # falls back to subject
        self.assertIn("always-read", always_body["tags"])

    def test_deliver_reader_skips_items_without_url(self):
        resp = mock.Mock(status_code=200, headers={}, text="")
        with mock.patch.dict(os.environ, {"READWISE_TOKEN": "tok"}, clear=True):
            with mock.patch.object(main.requests, "post", return_value=resp) as post:
                main.deliver_reader(
                    [{"headline": "No URL pick"}, {"url": "https://example.com/ok", "headline": "OK"}],
                    [{"headline": "No URL always"}],
                )
        # Only the single article with a URL should be pushed.
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["url"], "https://example.com/ok")

    def test_deliver_reader_honors_location_override(self):
        resp = mock.Mock(status_code=201, headers={}, text="")
        with mock.patch.dict(os.environ, {"READWISE_TOKEN": "t", "READWISE_READER_LOCATION": "shortlist"}, clear=True):
            with mock.patch.object(main.requests, "post", return_value=resp) as post:
                main.deliver_reader([{"url": "https://example.com/x", "headline": "X"}], [])
        self.assertEqual(post.call_args.kwargs["json"]["location"], "shortlist")


class ExtractJsonArrayTests(unittest.TestCase):
    """Regression guard for the select_articles 'no parseable JSON' failures."""

    @staticmethod
    def _blocks(*texts):
        return [SimpleNamespace(type="text", text=t) for t in texts]

    def test_plain_array(self):
        out = main._extract_json_array(self._blocks('[{"rank": 1, "headline": "A"}]'))
        self.assertEqual(out, [{"rank": 1, "headline": "A"}])

    def test_prefers_final_block_over_narration_brackets(self):
        # web_search narration has stray "[1]"; the real array is the last block.
        blocks = self._blocks(
            "Searching... found source [1] and [2] relevant.",
            'Here are the picks:\n[{"rank": 1, "headline": "Real"}]',
        )
        self.assertEqual(main._extract_json_array(blocks), [{"rank": 1, "headline": "Real"}])

    def test_strips_code_fence(self):
        blocks = self._blocks('```json\n[{"rank": 1}]\n```')
        self.assertEqual(main._extract_json_array(blocks), [{"rank": 1}])

    def test_truncated_array_returns_empty(self):
        # A max_tokens cutoff mid-array must NOT half-parse — return [].
        blocks = self._blocks('[{"rank": 1, "headline": "A"}, {"rank": 2, "headl')
        self.assertEqual(main._extract_json_array(blocks), [])

    def test_no_array_returns_empty(self):
        self.assertEqual(main._extract_json_array(self._blocks("no json here")), [])

    def test_ignores_object_only_response(self):
        # A bare object (not the expected list) shouldn't be returned as picks.
        self.assertEqual(main._extract_json_array(self._blocks('{"rank": 1}')), [])

    def test_ignores_nested_string_array_returns_outer_dicts(self):
        # The article objects carry nested arrays (e.g. signal_tags). The reverse
        # scan hits the *inner* ["ai","biotech"] span first; it must be rejected
        # (not dicts) and the outer article array returned instead — otherwise a
        # bare string list reaches `.get()` and crashes the run.
        blocks = self._blocks(
            '[{"rank": 1, "headline": "A", "signal_tags": ["ai", "biotech"]}]'
        )
        self.assertEqual(
            main._extract_json_array(blocks),
            [{"rank": 1, "headline": "A", "signal_tags": ["ai", "biotech"]}],
        )

    def test_ignores_top_level_string_array(self):
        # If the model returns headlines as bare strings, degrade to [] (caller
        # reports "no parseable") rather than handing strings downstream.
        self.assertEqual(
            main._extract_json_array(self._blocks('["Headline one", "Headline two"]')),
            [],
        )


class ReadwiseClientTests(unittest.TestCase):
    """readwise_client.fetch_export — pagination, auth, and 429 backoff."""

    @staticmethod
    def _resp(status=200, body=None, headers=None, text=""):
        resp = mock.Mock(status_code=status, headers=headers or {}, text=text)
        resp.json.return_value = body if body is not None else {}
        return resp

    def test_paginates_and_passes_updated_after(self):
        pages = [
            self._resp(body={"results": [{"user_book_id": 1}], "nextPageCursor": "c2"}),
            self._resp(body={"results": [{"user_book_id": 2}], "nextPageCursor": None}),
        ]
        request_fn = mock.Mock(side_effect=pages)

        docs = readwise_client.fetch_export(
            "tok", updated_after="2026-06-01T00:00:00Z", request_fn=request_fn
        )

        self.assertEqual([d["user_book_id"] for d in docs], [1, 2])
        self.assertEqual(request_fn.call_count, 2)
        first_params = request_fn.call_args_list[0].kwargs["params"]
        self.assertEqual(first_params["updatedAfter"], "2026-06-01T00:00:00Z")
        self.assertNotIn("pageCursor", first_params)
        second_params = request_fn.call_args_list[1].kwargs["params"]
        self.assertEqual(second_params["pageCursor"], "c2")
        headers = request_fn.call_args_list[0].kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Token tok")

    def test_429_honors_retry_after_then_succeeds(self):
        pages = [
            self._resp(status=429, headers={"Retry-After": "7"}),
            self._resp(body={"results": [{"user_book_id": 9}], "nextPageCursor": None}),
        ]
        request_fn = mock.Mock(side_effect=pages)
        sleeps = []

        docs = readwise_client.fetch_export(
            "tok", request_fn=request_fn, sleep_fn=sleeps.append
        )

        self.assertEqual(len(docs), 1)
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 7)

    def test_persistent_429_raises_after_bounded_retries(self):
        request_fn = mock.Mock(
            return_value=self._resp(status=429, headers={"Retry-After": "1"})
        )
        with self.assertRaises(readwise_client.ReadwiseError):
            readwise_client.fetch_export("tok", request_fn=request_fn, sleep_fn=lambda s: None)
        self.assertEqual(request_fn.call_count, readwise_client.MAX_RETRIES_PER_PAGE + 1)

    def test_401_raises_auth_error(self):
        request_fn = mock.Mock(return_value=self._resp(status=401))
        with self.assertRaises(readwise_client.ReadwiseAuthError):
            readwise_client.fetch_export("bad", request_fn=request_fn, sleep_fn=lambda s: None)

    def test_missing_token_raises_auth_error(self):
        with self.assertRaises(readwise_client.ReadwiseAuthError):
            readwise_client.fetch_export("", request_fn=mock.Mock())

    def test_runaway_pagination_raises_not_partial(self):
        request_fn = mock.Mock(
            return_value=self._resp(body={"results": [], "nextPageCursor": "again"})
        )
        with self.assertRaises(readwise_client.ReadwiseError):
            readwise_client.fetch_export(
                "tok", max_pages=3, request_fn=request_fn, sleep_fn=lambda s: None
            )
        self.assertEqual(request_fn.call_count, 3)


class ProcessReadwiseExemplarTests(unittest.TestCase):
    """Readwise highlights → positive_exemplar records in taste_evidence.json."""

    ARTICLE_DOC = {
        "user_book_id": 4321,
        "title": "Why Managed Care Margins Compress",
        "readable_title": "Why Managed Care Margins Compress",
        "author": "Analyst Person",
        "category": "articles",
        "source": "reader",
        "source_url": "https://example.com/mco-margins",
        "unique_url": "https://readwise.io/reader/shared/abc",
        "highlights": [
            {"text": "MLR floors bite in year two.", "note": "core thesis", "highlighted_at": "2026-06-20T10:00:00Z"},
            {"text": "Discarded junk", "is_discard": True, "highlighted_at": "2026-06-21T10:00:00Z"},
            {"text": "Repricing lags utilization by ~9 months.", "note": "", "highlighted_at": "2026-06-22T10:00:00Z"},
        ],
    }
    BOOK_DOC = {
        "user_book_id": 99,
        "title": "Some Investing Book",
        "category": "books",
        "source_url": "",
        "highlights": [{"text": "book highlight", "highlighted_at": "2026-06-22T10:00:00Z"}],
    }

    def test_build_exemplar_maps_article(self):
        record = process_readwise_exemplars.build_exemplar(
            self.ARTICLE_DOC, "2026-07-04T12:00:00Z"
        )
        self.assertEqual(record["kind"], "positive_exemplar")
        self.assertEqual(record["source_channel"], "readwise")
        self.assertEqual(record["title"], "Why Managed Care Margins Compress")
        self.assertEqual(record["url"], "https://example.com/mco-margins")
        self.assertEqual(record["note"], "core thesis")
        self.assertEqual(record["content_status"], "extracted")
        self.assertEqual(record["id"], project_data.evidence_id_for("readwise|4321"))
        meta = record["metadata"]
        # Discarded highlight excluded; remaining two joined chronologically.
        self.assertEqual(meta["highlight_count"], 2)
        self.assertEqual(
            meta["extracted_text_preview"],
            "MLR floors bite in year two. […] Repricing lags utilization by ~9 months.",
        )
        self.assertEqual(meta["latest_highlighted_at"], "2026-06-22T10:00:00Z")
        self.assertEqual(record["created_at"], "2026-07-04T12:00:00Z")

    def test_build_exemplar_keeps_books_out_of_article_loop(self):
        self.assertIsNone(
            process_readwise_exemplars.build_exemplar(self.BOOK_DOC, "2026-07-04T12:00:00Z")
        )

    def test_build_exemplar_skips_article_with_no_usable_highlights(self):
        doc = dict(self.ARTICLE_DOC, highlights=[{"text": "  ", "is_discard": False}])
        self.assertIsNone(process_readwise_exemplars.build_exemplar(doc, "2026-07-04T12:00:00Z"))

    def _run_ingest_in_tmpdir(self, docs, tmpdir):
        original_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            with mock.patch.object(
                process_readwise_exemplars, "fetch_export", return_value=docs
            ) as fetch:
                summary = process_readwise_exemplars.ingest("tok")
            return summary, fetch
        finally:
            os.chdir(original_cwd)

    def test_ingest_appends_evidence_and_advances_cursor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary, fetch = self._run_ingest_in_tmpdir(
                [self.ARTICLE_DOC, self.BOOK_DOC], tmpdir
            )
            self.assertEqual(summary["new_exemplars"], 1)
            self.assertEqual(summary["skipped_non_article"], 1)
            self.assertFalse(summary["truncated"])
            # First run uses the 30-day default lookback.
            self.assertTrue(fetch.call_args.kwargs["updated_after"])

            evidence = json.load(open(os.path.join(tmpdir, "taste_evidence.json")))
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["source_channel"], "readwise")

            state = json.load(open(os.path.join(tmpdir, "readwise_state.json")))
            self.assertIn("updated_after", state)
            self.assertEqual(state["last_run_added"], 1)

            # Second run: same doc returns, dedupe adds nothing.
            summary2, fetch2 = self._run_ingest_in_tmpdir([self.ARTICLE_DOC], tmpdir)
            self.assertEqual(summary2["new_exemplars"], 0)
            # Incremental: second run queries from the persisted cursor.
            self.assertEqual(
                fetch2.call_args.kwargs["updated_after"], state["updated_after"]
            )
            evidence = json.load(open(os.path.join(tmpdir, "taste_evidence.json")))
            self.assertEqual(len(evidence), 1)

    def test_ingest_cap_holds_cursor_back_so_overflow_drains(self):
        docs = [
            dict(
                self.ARTICLE_DOC,
                user_book_id=1000 + i,
                source_url=f"https://example.com/a{i}",
            )
            for i in range(process_readwise_exemplars.MAX_NEW_EXEMPLARS_PER_RUN + 5)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            summary, _ = self._run_ingest_in_tmpdir(docs, tmpdir)
            self.assertTrue(summary["truncated"])
            self.assertEqual(
                summary["new_exemplars"],
                process_readwise_exemplars.MAX_NEW_EXEMPLARS_PER_RUN,
            )
            state = json.load(open(os.path.join(tmpdir, "readwise_state.json")))
            self.assertNotIn("updated_after", state)  # cursor held back

            # Next run drains the remaining 5.
            summary2, _ = self._run_ingest_in_tmpdir(docs, tmpdir)
            self.assertEqual(summary2["new_exemplars"], 5)
            state = json.load(open(os.path.join(tmpdir, "readwise_state.json")))
            self.assertIn("updated_after", state)

    def test_main_without_token_warns_loudly_and_proceeds(self):
        env = {"SLACK_WEBHOOK_STATUS_REPORTS": "https://hooks.slack test"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(process_readwise_exemplars.requests, "post") as post:
                post.return_value = mock.Mock(raise_for_status=lambda: None)
                process_readwise_exemplars.main()  # must not raise
        post.assert_called_once()
        blocks = post.call_args.kwargs["json"]["blocks"]
        self.assertEqual(blocks[0]["type"], "section")
        self.assertIn("READWISE_TOKEN not set", blocks[0]["text"]["text"])

    def test_main_auth_error_alarms_but_exits_cleanly(self):
        env = {"READWISE_TOKEN": "bad", "SLACK_WEBHOOK_STATUS_REPORTS": "https://hooks"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                process_readwise_exemplars,
                "ingest",
                side_effect=readwise_client.ReadwiseAuthError("rejected"),
            ):
                with mock.patch.object(process_readwise_exemplars.requests, "post") as post:
                    post.return_value = mock.Mock(raise_for_status=lambda: None)
                    process_readwise_exemplars.main()  # must not raise
        post.assert_called_once()
        self.assertIn("token rejected", post.call_args.kwargs["json"]["text"])


class PaywallStubTest(unittest.TestCase):
    def test_statplus_teaser_is_flagged(self):
        # STAT+ intro-teaser that clears the old <1500 generic gate but is gated.
        teaser = ("Novartis CEO joins Anthropic board. " * 40 +
                  " This article is exclusive to STAT+ subscribers. "
                  "Subscribe to read the full story. Already a subscriber? Log in.")
        self.assertGreater(len(teaser), 1500)
        self.assertTrue(main._is_paywall_stub(teaser))

    def test_full_article_mentioning_paywall_not_flagged(self):
        # A genuinely-full body that merely mentions STAT+ once must NOT be nuked.
        full = "Real article body sentence. " * 400 + " (mentions STAT+ once)"
        self.assertGreater(len(full), 4000)
        self.assertFalse(main._is_paywall_stub(full))

    def test_generic_short_wall_still_flagged(self):
        self.assertTrue(main._is_paywall_stub("Are you a robot? Please complete the captcha."))

    def test_subscribers_only_teaser_flagged(self):
        t = "Lead paragraph. " * 30 + " This content is for subscribers only."
        self.assertTrue(main._is_paywall_stub(t))

    def test_clean_short_text_not_flagged(self):
        self.assertFalse(main._is_paywall_stub("A short but clean article with real content and no wall."))


class GmailScanFailLoudTests(unittest.TestCase):
    """A hard Gmail API failure must flag the run partial, not degrade silently."""

    def test_gmail_scan_records_partial_on_hard_failure(self):
        main._RUN_STATE["partial_reasons"].clear()
        with mock.patch.object(main, "fetch_newsletters",
                               side_effect=Exception("gmail 500")):
            items = main.gmail_scan()
        self.assertEqual(items, [])
        self.assertTrue(
            any("Gmail scan failed" in r for r in main._RUN_STATE["partial_reasons"]),
            "expected a partial_reason to be recorded on hard Gmail failure",
        )
        main._RUN_STATE["partial_reasons"].clear()


class DedupeDistinctHeadlineTests(unittest.TestCase):
    """Distinct newsletter editions that share a first URL must not collapse."""

    def test_shared_first_url_distinct_headlines_both_kept(self):
        # Two distinct Fierce editions whose first extracted link is the same
        # sponsor/webinar URL -> identical candidate_id. They must survive.
        gmail_items = [
            {
                "source_name": "Fierce Biotech",
                "subject": "| 04.14.26 | J&J dual powerhouse; Lilly ADC buyout",
                "snippet": "edition one",
                "urls": ["https://sponsor.example.com/webinar?pk=promo"],
                "tier": 1,
            },
            {
                "source_name": "Fierce Biotech",
                "subject": "| 04.13.26 | Regeneron radiopharma; FDA update",
                "snippet": "edition two",
                "urls": ["https://sponsor.example.com/webinar?pk=promo"],
                "tier": 1,
            },
        ]
        gmail, _ = main.build_structured_candidates(gmail_items, [], "2026-04-14", {})
        headlines = {c["headline"] for c in gmail}
        self.assertEqual(len(gmail), 2, "distinct editions were collapsed by dedupe")
        self.assertEqual(len(headlines), 2)

    def test_true_duplicate_same_headline_and_url_collapses(self):
        # Same article delivered to two plus-aliases: identical headline + URL.
        dup = {
            "source_name": "Fierce Biotech",
            "subject": "| 04.14.26 | J&J dual powerhouse",
            "snippet": "same article",
            "urls": ["https://sponsor.example.com/webinar?pk=promo"],
            "tier": 1,
        }
        gmail, _ = main.build_structured_candidates([dup, dict(dup)], [], "2026-04-14", {})
        self.assertEqual(len(gmail), 1, "plus-alias duplicate should still collapse")


class CheckUrlLiveDeadEndTests(unittest.TestCase):
    """The pre-delivery liveness probe must reject homepage/ad-tracker dead ends."""

    def _resp(self, status_code, final_url):
        return SimpleNamespace(
            status_code=status_code, url=final_url, close=lambda: None
        )

    def test_homepage_redirect_is_dead(self):
        import url_resolver
        resp = self._resp(200, "https://publisher.example.com/")
        with mock.patch.object(url_resolver.requests, "head", return_value=resp):
            self.assertFalse(
                url_resolver.check_url_live("https://trk1.publisher.example.com/T/tok")
            )

    def test_real_article_path_is_live(self):
        import url_resolver
        resp = self._resp(200, "https://publisher.example.com/2026/04/14/real-story")
        with mock.patch.object(url_resolver.requests, "head", return_value=resp):
            self.assertTrue(
                url_resolver.check_url_live("https://publisher.example.com/2026/04/14/real-story")
            )

    def test_ad_tracker_host_is_dead(self):
        import url_resolver
        resp = self._resp(200, "https://p.liadm.com/anything")
        with mock.patch.object(url_resolver.requests, "head", return_value=resp):
            self.assertFalse(
                url_resolver.check_url_live("https://trk1.publisher.example.com/T/tok")
            )


class RssFeedHealthTests(unittest.TestCase):
    """A total RSS outage must be distinguishable from a quiet zero-item day."""

    def test_all_feeds_erroring_reports_zero_feeds_ok(self):
        import rss_feeds

        boom = SimpleNamespace(bozo=1, bozo_exception=Exception("down"), entries=[])
        with mock.patch.object(rss_feeds.feedparser, "parse", return_value=boom):
            items, health = rss_feeds.fetch_rss_feeds_with_health()

        self.assertEqual(items, [])
        self.assertEqual(health["feeds_ok"], 0)
        self.assertEqual(health["feeds_total"], len(rss_feeds.RSS_FEEDS))

    def test_healthy_feed_with_no_recent_items_still_counts_ok(self):
        import rss_feeds

        # Parses cleanly but every entry is older than the window -> 0 items,
        # yet feeds_ok must be > 0 (a quiet day, NOT an outage).
        old = SimpleNamespace(
            bozo=0,
            entries=[SimpleNamespace(get=lambda k, d=None: "", published_parsed=(2000, 1, 1, 0, 0, 0))],
        )
        with mock.patch.object(rss_feeds.feedparser, "parse", return_value=old):
            items, health = rss_feeds.fetch_rss_feeds_with_health()

        self.assertEqual(items, [])
        self.assertGreater(health["feeds_ok"], 0)

    def test_rss_scan_flags_partial_on_total_outage(self):
        main._RUN_STATE["partial_reasons"].clear()
        with mock.patch("rss_feeds.fetch_rss_feeds_with_health",
                        return_value=([], {"feeds_ok": 0, "feeds_total": 30})):
            items = main.rss_scan()
        self.assertEqual(items, [])
        self.assertTrue(
            any("RSS total outage" in r for r in main._RUN_STATE["partial_reasons"]),
            "a total feed outage should flag the run partial",
        )
        main._RUN_STATE["partial_reasons"].clear()

    def test_rss_scan_quiet_day_is_not_partial(self):
        main._RUN_STATE["partial_reasons"].clear()
        with mock.patch("rss_feeds.fetch_rss_feeds_with_health",
                        return_value=([], {"feeds_ok": 30, "feeds_total": 30})):
            main.rss_scan()
        self.assertFalse(
            any("RSS total outage" in r for r in main._RUN_STATE["partial_reasons"]),
            "a quiet day (all feeds OK, no items) must not be flagged an outage",
        )
        main._RUN_STATE["partial_reasons"].clear()


class ResolverTransientCacheTests(unittest.TestCase):
    """A transient transport failure must NOT be cached as a permanent no-op."""

    def test_resolve_one_returns_transient_sentinel_on_network_error(self):
        import url_resolver

        with mock.patch.object(url_resolver.requests, "head",
                               side_effect=url_resolver.requests.exceptions.Timeout()), \
             mock.patch.object(url_resolver.requests, "get",
                               side_effect=url_resolver.requests.exceptions.Timeout()):
            result = url_resolver._resolve_one("https://links.example.com/T/tok")
        self.assertIs(result, url_resolver.TRANSIENT_FAILURE)

    def test_transient_failure_not_written_to_cache(self):
        # Exercises the real _resolve_one + resolve_urls path: a genuine
        # network timeout must leave the URL uncached so the next run retries
        # (the OLD code cached url->url, permanently suppressing retries).
        import url_resolver

        url = "https://links.example.com/T/tok"
        timeout = url_resolver.requests.exceptions.Timeout
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with mock.patch.object(url_resolver.requests, "head", side_effect=timeout()), \
                     mock.patch.object(url_resolver.requests, "get", side_effect=timeout()):
                    out = url_resolver.resolve_urls([url])
                # Original URL preserved so the pipeline doesn't break...
                self.assertEqual(out, [url])
                # ...but nothing cached, so the next run retries.
                cached = {}
                if os.path.exists(url_resolver.CACHE_PATH):
                    cached = json.loads(open(url_resolver.CACHE_PATH).read())
                self.assertNotIn(url, cached, "a transient failure must not be cached")
            finally:
                os.chdir(original_cwd)

    def test_real_resolution_is_cached(self):
        import url_resolver

        url = "https://links.example.com/T/tok"
        final = "https://publisher.example.com/2026/07/18/story"
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with mock.patch.object(url_resolver, "_resolve_one", return_value=final):
                    out = url_resolver.resolve_urls([url])
                self.assertEqual(out, [final])
                cache = json.loads(open(url_resolver.CACHE_PATH).read())
                self.assertEqual(cache.get(url), final)
            finally:
                os.chdir(original_cwd)


class DeliveredStateTests(unittest.TestCase):
    """Rolling cross-run sent-state: bounded window + hard id cap."""

    def test_record_and_recent_ids_roundtrip(self):
        state = {"delivered": []}
        state = project_data.record_delivered(state, ["a", "b"], "2026-07-18")
        recent = project_data.recently_delivered_ids(state, "2026-07-18")
        self.assertEqual(recent, {"a", "b"})

    def test_window_prunes_old_ids(self):
        state = {"delivered": [
            {"id": "old", "date": "2026-06-01"},
            {"id": "fresh", "date": "2026-07-17"},
        ]}
        # Re-record on a later day with a 14-day window -> "old" drops out.
        state = project_data.record_delivered(state, [], "2026-07-18", window_days=14)
        ids = {e["id"] for e in state["delivered"]}
        self.assertIn("fresh", ids)
        self.assertNotIn("old", ids)

    def test_recent_ids_respects_window(self):
        state = {"delivered": [
            {"id": "old", "date": "2026-06-01"},
            {"id": "fresh", "date": "2026-07-17"},
        ]}
        recent = project_data.recently_delivered_ids(state, "2026-07-18", window_days=14)
        self.assertEqual(recent, {"fresh"})

    def test_id_cap_bounds_growth(self):
        state = {"delivered": []}
        many = [f"id{i}" for i in range(50)]
        state = project_data.record_delivered(state, many, "2026-07-18", max_ids=10)
        self.assertLessEqual(len(state["delivered"]), 10)


class CrossRunDedupEndToEndTests(unittest.TestCase):
    """End-to-end: an article delivered today is excluded from the next run's
    selection — and the recorded id matches the exclusion key even when Claude
    returns a different-cased/relabelled source for the same URL."""

    def test_delivered_article_excluded_next_run(self):
        gmail_items = [{
            "source_name": "Endpoints News",
            "subject": "Big pharma buys biotech",
            "snippet": "deal",
            "urls": ["https://endpts.com/big-pharma-buys-biotech"],
            "tier": 1,
        }]

        # Build the candidate exactly as the pipeline does to get its id.
        gmail, _ = main.build_structured_candidates(gmail_items, [], "2026-07-18", {})
        candidate_id = gmail[0]["candidate_id"]

        # Simulate what got delivered: same URL, but Claude relabelled the
        # source ("Endpoints" vs "Endpoints News") -> article_id_for(url,source)
        # would diverge; delivered_candidate_ids must resolve back by URL.
        delivered = [{
            "url": "https://endpts.com/big-pharma-buys-biotech",
            "source": "Endpoints",
            "article_id": project_data.article_id_for(
                "https://endpts.com/big-pharma-buys-biotech", "Endpoints"),
        }]
        recorded = main.delivered_candidate_ids(delivered, gmail)
        self.assertIn(candidate_id, recorded,
                      "recorded id must match the candidate/exclusion key")

        # Next run: the candidate is filtered out before selection.
        state = project_data.record_delivered({"delivered": []}, recorded, "2026-07-18")
        exclude = project_data.recently_delivered_ids(state, "2026-07-19")
        gmail2, _ = main.build_structured_candidates(gmail_items, [], "2026-07-19", {})
        survivors = [c for c in gmail2 if c["candidate_id"] not in exclude]
        self.assertEqual(survivors, [],
                         "a just-delivered article should not survive to the next selection")


class CriteriaCommitBeforeCloseTests(unittest.TestCase):
    """The GitHub issue must only be closed AFTER durable state is committed."""

    def _run(self, commit_ok):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            original_token = os.environ.get("GITHUB_TOKEN")
            try:
                os.chdir(tmpdir)
                os.environ["GITHUB_TOKEN"] = "test-token"
                with open("criteria_update_state.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "pending": {"proposal_id": "p1", "status": "pending"},
                        "history": [],
                    }, f)
                with open("selection_criteria.md", "w", encoding="utf-8") as f:
                    f.write("old\n")
                with open("selection_criteria_proposed.md", "w", encoding="utf-8") as f:
                    f.write("new\n")

                issue = {"number": 7, "title": "Criteria Update: accept p1", "body": ""}
                get_resp = mock.Mock()
                get_resp.raise_for_status.return_value = None
                get_resp.json.return_value = [issue]

                patch_mock = mock.Mock()
                with mock.patch.object(process_criteria_feedback.requests, "get", return_value=get_resp), \
                     mock.patch.object(process_criteria_feedback.requests, "patch", patch_mock), \
                     mock.patch.object(process_criteria_feedback, "commit_durable_state", return_value=commit_ok):
                    process_criteria_feedback.main()
                return patch_mock
            finally:
                os.chdir(original_cwd)
                if original_token is None:
                    os.environ.pop("GITHUB_TOKEN", None)
                else:
                    os.environ["GITHUB_TOKEN"] = original_token

    def test_issue_closed_when_commit_succeeds(self):
        patch_mock = self._run(commit_ok=True)
        patch_mock.assert_called_once()

    def test_issue_left_open_when_commit_fails(self):
        patch_mock = self._run(commit_ok=False)
        patch_mock.assert_not_called()

    def test_commit_durable_state_false_on_git_failure(self):
        # No git repo in a bare tmpdir -> git add/commit fail -> returns False.
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with open("selection_criteria.md", "w", encoding="utf-8") as f:
                    f.write("x\n")
                with mock.patch.object(
                    process_criteria_feedback.subprocess, "run",
                    side_effect=Exception("not a git repo"),
                ):
                    ok = process_criteria_feedback.commit_durable_state(
                        ["selection_criteria.md"], "msg")
                self.assertFalse(ok)
            finally:
                os.chdir(original_cwd)


class BrokenMainSlotSubstitutionTests(unittest.TestCase):
    """A dead link in a main slot must be replaced from the also-considered
    queue, not shipped to the reader on an otherwise-`ok` run (JP 2026-07-19)."""

    def _article(self, slot, source, url):
        return {
            "article_id": f"a{slot}", "headline": f"Headline {slot}",
            "source": source, "url": url, "slot": slot,
            "summary": "s", "why_it_matters": "w",
            "signal_tags": [], "reading_time": "5 min",
        }

    def _cand(self, name, url, score):
        return {
            "source_name": name, "headline": f"Triage {name}",
            "primary_url": url, "triage_score": score,
            "snippet": f"snippet for {name}", "category": "healthcare",
        }

    def _run(self, articles, triage, liveness, exclude_ids=None):
        """Run validate_delivery_urls in a tmpdir with a stubbed liveness probe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                os.makedirs("artifacts", exist_ok=True)
                with mock.patch.object(
                    main, "check_urls_live",
                    side_effect=lambda urls, timeout=3: {u: liveness.get(u, True) for u in urls},
                ):
                    arts, tri, always, subs = main.validate_delivery_urls(
                        articles, triage, [], [], exclude_ids=exclude_ids
                    )
                log = json.load(open("artifacts/url_validation_log.json", encoding="utf-8"))
                return arts, tri, log[-1]
            finally:
                os.chdir(original_cwd)

    def test_recently_delivered_candidate_is_never_promoted(self):
        """The cross-run dedupe filters select_articles() but NOT the triage
        queue, so the promotion path has to re-apply it or a slot can silently
        re-deliver yesterday's article (codex 2026-07-20)."""
        articles = [self._article(1, "Alpha", "https://alpha.test/dead")]
        triage = [
            {**self._cand("Gamma", "https://gamma.test/ok", 9), "candidate_id": "cid-gamma"},
            {**self._cand("Delta", "https://delta.test/ok", 1), "candidate_id": "cid-delta"},
        ]
        arts, tri, log = self._run(
            articles, triage, {"https://alpha.test/dead": False},
            exclude_ids={"cid-gamma"},
        )
        self.assertEqual(
            arts[0]["source"], "Delta",
            "Gamma scores higher but was delivered recently — must be skipped",
        )

    def test_all_candidates_excluded_falls_back_to_shipping_broken(self):
        articles = [self._article(1, "Alpha", "https://alpha.test/dead")]
        triage = [
            {**self._cand("Gamma", "https://gamma.test/ok", 9), "candidate_id": "cid-gamma"},
        ]
        arts, tri, log = self._run(
            articles, triage, {"https://alpha.test/dead": False},
            exclude_ids={"cid-gamma"},
        )
        self.assertEqual(arts[0]["source"], "Alpha", "slot preserved")
        self.assertEqual(log["broken"]["article_warnings"], 1)
        self.assertEqual(log["broken"]["article_substituted"], 0)

    def test_broken_slot_is_replaced_by_best_live_candidate(self):
        articles = [
            self._article(1, "Alpha", "https://alpha.test/dead"),
            self._article(2, "Beta", "https://beta.test/ok"),
        ]
        triage = [
            self._cand("Gamma", "https://gamma.test/ok", 5),
            self._cand("Delta", "https://delta.test/ok", 9),
        ]
        arts, tri, log = self._run(
            articles, triage, {"https://alpha.test/dead": False},
        )
        # Highest triage_score (Delta, 9) wins the slot, not queue order.
        self.assertEqual(arts[0]["source"], "Delta")
        self.assertEqual(arts[0]["url"], "https://delta.test/ok")
        self.assertEqual(arts[0]["slot"], 1, "slot number must be preserved")
        self.assertEqual(arts[1]["source"], "Beta", "healthy slot untouched")
        # Promoted candidate must not also remain in the triage queue.
        self.assertEqual([c["source_name"] for c in tri], ["Gamma"])
        self.assertEqual(log["broken"]["article_substituted"], 1)
        self.assertEqual(log["broken"]["article_warnings"], 0,
                         "a rescued slot is not a 'shipped broken' warning")
        self.assertEqual(log["warned_articles"], [])

    def test_substitute_never_duplicates_a_surviving_source(self):
        articles = [
            self._article(1, "Alpha", "https://alpha.test/dead"),
            self._article(2, "Delta", "https://delta.test/ok"),
        ]
        # Delta scores highest but is already in slot 2 — must be skipped.
        triage = [
            self._cand("Delta", "https://delta.test/other", 9),
            self._cand("Gamma", "https://gamma.test/ok", 5),
        ]
        arts, tri, log = self._run(
            articles, triage, {"https://alpha.test/dead": False},
        )
        self.assertEqual(arts[0]["source"], "Gamma")
        self.assertEqual(log["broken"]["article_substituted"], 1)

    def test_broken_triage_candidate_is_never_promoted(self):
        articles = [self._article(1, "Alpha", "https://alpha.test/dead")]
        triage = [
            self._cand("Gamma", "https://gamma.test/dead", 9),
            self._cand("Delta", "https://delta.test/ok", 1),
        ]
        arts, tri, log = self._run(
            articles, triage,
            {"https://alpha.test/dead": False, "https://gamma.test/dead": False},
        )
        self.assertEqual(arts[0]["source"], "Delta",
                         "must not promote a candidate whose own URL is dead")
        self.assertEqual(tri, [], "broken Gamma dropped, Delta promoted out")

    def test_ships_broken_when_no_substitute_available(self):
        """Fallback must still preserve the slot — an empty slot is worse."""
        articles = [self._article(1, "Alpha", "https://alpha.test/dead")]
        arts, tri, log = self._run(
            articles, [], {"https://alpha.test/dead": False},
        )
        self.assertEqual(len(arts), 1, "slot preserved rather than emptied")
        self.assertEqual(arts[0]["source"], "Alpha")
        self.assertEqual(log["broken"]["article_warnings"], 1)
        self.assertEqual(log["broken"]["article_substituted"], 0)
        self.assertEqual(log["warned_articles"][0]["source"], "Alpha")

    def test_clean_run_substitutes_nothing(self):
        articles = [self._article(1, "Alpha", "https://alpha.test/ok")]
        triage = [self._cand("Gamma", "https://gamma.test/ok", 5)]
        arts, tri, log = self._run(articles, triage, {})
        self.assertEqual(arts[0]["source"], "Alpha")
        self.assertEqual([c["source_name"] for c in tri], ["Gamma"])
        self.assertEqual(log["broken"]["article_substituted"], 0)
        self.assertEqual(log["broken"]["article_warnings"], 0)

    def test_two_broken_slots_get_distinct_substitutes(self):
        articles = [
            self._article(1, "Alpha", "https://alpha.test/dead"),
            self._article(2, "Beta", "https://beta.test/dead"),
        ]
        triage = [
            self._cand("Gamma", "https://gamma.test/ok", 9),
            self._cand("Delta", "https://delta.test/ok", 5),
        ]
        arts, tri, log = self._run(
            articles, triage,
            {"https://alpha.test/dead": False, "https://beta.test/dead": False},
        )
        self.assertEqual(arts[0]["source"], "Gamma")
        self.assertEqual(arts[1]["source"], "Delta")
        self.assertEqual(tri, [], "both promoted out of the queue")
        self.assertEqual(log["broken"]["article_substituted"], 2)


class WeeklyReportCountsSubstitutionsTests(unittest.TestCase):
    """A rescued main slot still means the source shipped a dead link. The
    weekly URL-health report must not read as a clean week just because
    substitution hid the breakage from the reader."""

    def _report_for(self, entry):
        """build_report() takes no args — it derives its window from
        _past_7_days() and reads the log via _load_json. Stub both so the
        report sees exactly this one entry."""
        import weekly_report
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                os.makedirs("artifacts", exist_ok=True)
                with mock.patch.object(
                    weekly_report, "_past_7_days", return_value=[entry["date"]]
                ), mock.patch.object(
                    weekly_report, "_load_json",
                    side_effect=lambda path, default=None: (
                        [entry] if path == weekly_report.URL_VALIDATION_LOG
                        else (default if default is not None else [])
                    ),
                ):
                    report = weekly_report.build_report()
                return report["url_validation"]
            finally:
                os.chdir(original_cwd)

    def test_substituted_slots_count_as_broken_and_name_the_source(self):
        uv = self._report_for({
            "date": "2026-07-19",
            "checked_slots": 12,
            "broken": {
                "article_warnings": 0,
                "article_substituted": 2,
                "triage_dropped": 0,
                "always_read_dropped": 0,
                "substack_dropped": 0,
            },
            "warned_articles": [],
            "substituted_articles": [
                {"broken_source": "Fierce Pharma", "slot": 1},
                {"broken_source": "Fierce Pharma", "slot": 2},
            ],
        })
        self.assertEqual(uv["total_broken"], 2,
                         "rescued slots must still count as broken URLs")
        self.assertEqual(uv["surfaces"]["article_substituted"], 2)
        self.assertEqual(uv["top_warned_sources"], [("Fierce Pharma", 2)],
                         "a chronically-broken source must still be named")

    def test_legacy_log_entries_without_the_new_keys_still_work(self):
        uv = self._report_for({
            "date": "2026-07-19",
            "checked_slots": 8,
            "broken": {
                "article_warnings": 1,
                "triage_dropped": 1,
                "always_read_dropped": 0,
                "substack_dropped": 0,
            },
            "warned_articles": [{"source": "Old Source"}],
        })
        self.assertEqual(uv["surfaces"]["article_substituted"], 0)
        self.assertEqual(uv["total_broken"], 2)
        self.assertEqual(uv["top_warned_sources"], [("Old Source", 1)])


if __name__ == "__main__":
    unittest.main()


# --- preference-model timestamp churn (2026-07-25) --------------------------

def test_unchanged_preferences_do_not_restamp_timestamps():
    """A no-op learning run must produce a no-op diff.

    Stamping `updated_at`/`last_updated` unconditionally made the GH Actions
    run and the local Dropbox taste task emit commits that differed by nothing
    but the clock -- and then conflict. Six local commits accumulated carrying
    zero information.
    """
    import copy
    from preference_learning import apply_evidence

    before = {
        "version": 2,
        "updated_at": "2026-07-20T10:00:00Z",
        "topic_preferences": [{
            "name": "corporate governance", "strength": "strong",
            "evidence_ids": ["ev_1"], "last_updated": "2026-07-20T10:00:00Z",
        }],
        "source_preferences": [], "style_preferences": [], "avoid_patterns": [],
        "evidence_summary": None,
    }
    evidence = [{"id": "ev_1", "title": "corporate governance piece",
                 "note": "", "kind": "positive_exemplar"}]

    first = apply_evidence(copy.deepcopy(before), evidence, "2026-07-25T10:00:00Z")
    # Seed the summary the first pass computes, then re-run on identical input.
    stable = copy.deepcopy(first)
    second = apply_evidence(copy.deepcopy(stable), evidence, "2026-07-26T11:11:11Z")

    assert second == stable, "identical evidence must leave the model byte-identical"


def test_a_real_change_still_stamps():
    from preference_learning import apply_evidence

    base = {
        "version": 2, "updated_at": "2026-07-20T10:00:00Z",
        "topic_preferences": [{
            "name": "biotech", "strength": "weak", "evidence_ids": [],
            "last_updated": "2026-07-20T10:00:00Z",
        }],
        "source_preferences": [], "style_preferences": [], "avoid_patterns": [],
        "evidence_summary": None,
    }
    out = apply_evidence(base, [{"id": "ev_9", "title": "biotech breakthrough",
                                 "note": "", "kind": "positive_exemplar"}],
                         "2026-07-25T10:00:00Z")
    assert out["topic_preferences"][0]["evidence_ids"] == ["ev_9"]
    assert out["updated_at"] != "2026-07-20T10:00:00Z"


class VerifySlotDeferralTests(unittest.TestCase):
    """A candidate that fails ONLY on slot fit must be re-offered to its own slot.

    verify_shortlist walks the shortlist in rank order and verifies each
    candidate against whichever slot is currently being filled, discarding
    anything that fails. So an article excellent for Slot 1 that happens to
    surface while Slot 3 is being filled is rejected as off-theme and burned --
    it can never fill the slot it was right for.

    Measured on artifacts/verification_log.json since 2026-05-01: 89 of 411
    failures (21.7%) are this class, and the verifier's own reasons name the
    slot the article belonged to. Casualties include "Sun Pharma signs $11.75B
    Organon buyout" and a Biogen tau Phase 2 readout -- both rejected FOR SLOT 3
    while the stated reason was that they belonged in Slot 1.
    """

    def _client(self, verdicts, seen_slots):
        class _Msg:
            def __init__(self, text):
                self.content = [SimpleNamespace(type="text", text=text)]

        class _Messages:
            def create(_self, **kw):
                prompt = kw["messages"][0]["content"]
                m = re.search(r"TARGET SLOT: Slot (\d)", prompt)
                seen_slots.append(int(m.group(1)) if m else None)
                return _Msg(json.dumps(verdicts.pop(0)))

        return SimpleNamespace(messages=_Messages())

    @staticmethod
    def _ok(reason):
        return {"pass": True, "reason": reason, "summary": "a",
                "why_it_matters": "b", "reading_time": "3 min"}

    @staticmethod
    def _no(reason, best_slot=None):
        v = {"pass": False, "reason": reason, "summary": "",
             "why_it_matters": "", "reading_time": ""}
        if best_slot is not None:
            v["best_slot"] = best_slot
        return v

    def _run(self, cands, verdicts):
        import main
        seen = []
        client = self._client(verdicts, seen)
        with mock.patch.object(main, "fetch_article_text",
                               return_value=("full text " * 60, "trafilatura")) as fetch,              tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            os.chdir(td)
            try:
                out = main.verify_shortlist(cands, "crit", "", "", client)
            finally:
                os.chdir(cwd)
        return out, seen, fetch

    @staticmethod
    def _c(rank, headline, source, url):
        return {"rank": rank, "headline": headline, "source": source, "url": url,
                "summary": "s" * 80, "why_it_matters": "w"}

    def test_in_order_candidates_still_fill_slots_normally(self):
        cands = [self._c(1, "Pharma M&A", "Endpoints", "https://x.test/p"),
                 self._c(2, "Macro note", "FT", "https://x.test/m"),
                 self._c(3, "Model release", "TechCo", "https://x.test/a")]
        verdicts = [self._ok("hc"), self._ok("macro"), self._ok("ai"),
                    self._no("no wildcard")]
        out, _, _ = self._run(cands, verdicts)
        self.assertEqual([a["slot"] for a in out], [1, 2, 3])

    def test_article_rejected_for_the_current_slot_is_retried_on_its_best_slot(self):
        cands = [self._c(1, "Model release", "TechCo", "https://x.test/a"),
                 self._c(2, "Pharma M&A", "Endpoints", "https://x.test/p"),
                 self._c(3, "Macro note", "FT", "https://x.test/m")]
        verdicts = [self._no("targets Slot 3 (Tech/AI), not Slot 1", best_slot=3),
                    self._ok("hc"), self._ok("macro"), self._ok("ai on retry"),
                    self._no("no wildcard")]
        out, seen, fetch = self._run(cands, verdicts)

        by_slot = {a["slot"]: a["headline"] for a in out}
        self.assertEqual(by_slot.get(3), "Model release",
                         "the AI article must fill Slot 3, not be discarded")
        self.assertIn(3, seen, "it must actually be re-verified against Slot 3")
        self.assertEqual(fetch.call_count, 3,
                         "one fetch per URL -- extraction is the expensive, "
                         "fragile half and must not be repeated on retry")

    def test_a_parked_article_is_not_retried_forever(self):
        cands = [self._c(1, "AI thing", "TechCo", "https://x.test/a"),
                 self._c(2, "Pharma", "Endpoints", "https://x.test/p"),
                 self._c(3, "Macro", "FT", "https://x.test/m")]
        verdicts = [self._no("belongs Slot 3", best_slot=3), self._ok("hc"),
                    self._ok("macro"), self._no("thin on retry too", best_slot=3),
                    self._no("no wildcard")]
        out, _, _ = self._run(cands, verdicts)
        self.assertNotIn("AI thing", [a["headline"] for a in out])
        self.assertLessEqual(len(verdicts), 1,
                             "must not loop re-verifying the same item")

    def test_parked_article_does_not_bypass_source_dedup(self):
        """A parked item still competes under the one-article-per-source rule."""
        cands = [self._c(1, "AI thing", "TechCo", "https://x.test/a"),
                 self._c(2, "Pharma", "Endpoints", "https://x.test/p"),
                 self._c(3, "Macro", "FT", "https://x.test/m"),
                 self._c(4, "Other AI", "TechCo", "https://x.test/a2")]
        verdicts = [self._no("belongs Slot 3", best_slot=3), self._ok("hc"),
                    self._ok("macro"), self._ok("ai on retry"),
                    self._no("no wildcard")]
        out, _, _ = self._run(cands, verdicts)
        sources = [a["source"] for a in out]
        self.assertEqual(len(sources), len(set(sources)), "no duplicate source")


# --- #261: a source must never be alarmed and excused in the same report ----

def test_slow_cadence_source_is_not_in_the_alarm_list():
    """Board #261. Consilient Observer is monthly and was rendered TWICE:
    under `Missing sources` in alarm red / a Slack :warning:, and again under
    "Quiet this week (monthly/quarterly cadence - normal)"."""
    from weekly_report import classify_missing_sources
    all_names = {"Consilient Observer", "Value Investors Insight", "MBI"}
    seen = set()
    always = {"Consilient Observer", "Value Investors Insight", "MBI"}
    freq = {"Consilient Observer": "monthly",
            "Value Investors Insight": "monthly",
            "MBI": "weekly"}
    missing, missing_ar, quiet, quiet_ar = classify_missing_sources(
        all_names, seen, always, freq)
    assert missing == ["MBI"], "a monthly source is not a missing source"
    assert missing_ar == ["MBI"]
    assert quiet == ["Consilient Observer", "Value Investors Insight"]
    assert quiet_ar == ["Consilient Observer", "Value Investors Insight"]
    # the actual defect: no name may appear in both lists
    assert not (set(missing) & set(quiet))


def test_a_weekly_source_going_quiet_still_alarms():
    """The fix must not silence the alarm it exists to raise (#72 Fierce)."""
    from weekly_report import classify_missing_sources
    missing, missing_ar, quiet, _ = classify_missing_sources(
        {"Fierce Pharma"}, set(), {"Fierce Pharma"}, {"Fierce Pharma": "daily"})
    assert missing == ["Fierce Pharma"]
    assert missing_ar == ["Fierce Pharma"]
    assert quiet == []


def test_a_source_with_no_declared_cadence_still_alarms():
    """An unknown frequency is not evidence of a slow cadence."""
    from weekly_report import classify_missing_sources
    missing, _, quiet, _ = classify_missing_sources(
        {"Mystery"}, set(), set(), {})
    assert missing == ["Mystery"] and quiet == []


def test_a_seen_source_is_neither_missing_nor_quiet():
    from weekly_report import classify_missing_sources
    missing, missing_ar, quiet, quiet_ar = classify_missing_sources(
        {"MBI"}, {"MBI"}, {"MBI"}, {"MBI": "weekly"})
    assert missing == [] and missing_ar == [] and quiet == [] and quiet_ar == []


# --- #261 half 2: a dropped URL must be identifiable ------------------------

def test_dropped_items_are_named_not_just_counted():
    """Board #261's "6 broken always-read URLs" could be counted but never
    fixed: the three drop buckets logged a count and no identity."""
    from main import _dropped_detail
    always = [{"source": "Consilient Observer", "headline": "H1",
               "url": "https://dead.example/1"},
              {"source": "MBI", "headline": "H2", "url": "https://ok.example"}]
    triage = [{"source_name": "Stratechery", "title": "T1", "url": "https://x/2"}]
    out = _dropped_detail([(always, {0}, "always_read"),
                           (triage, {0}, "triage"),
                           ([], set(), "substack")])
    assert len(out) == 2
    ar = [d for d in out if d["surface"] == "always_read"][0]
    assert ar["source"] == "Consilient Observer"
    assert ar["url"] == "https://dead.example/1"
    tr = [d for d in out if d["surface"] == "triage"][0]
    assert tr["source"] == "Stratechery"      # reads source_name too
    assert tr["headline"] == "T1"             # reads title too


def test_dropped_detail_is_empty_when_nothing_dropped():
    from main import _dropped_detail
    assert _dropped_detail([([{"url": "u"}], set(), "always_read")]) == []


def test_dropped_detail_never_raises_on_a_bad_index():
    """This runs inside delivery; a logging detail must not take the digest down."""
    from main import _dropped_detail
    out = _dropped_detail([([{"url": "u"}], {0, 5, -1}, "always_read")])
    assert len(out) == 1 and out[0]["url"] == "u"
