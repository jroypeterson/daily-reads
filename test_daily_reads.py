import json
import os
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
import project_data


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
                     mock.patch.object(process_criteria_feedback.requests, "patch", return_value=mock.Mock()):
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


if __name__ == "__main__":
    unittest.main()
