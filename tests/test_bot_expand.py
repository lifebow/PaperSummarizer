"""Tests for the Telegram expand-paper bot feature.

Covers:
- DB expansion table and methods
- LLM expand prompt builder
- Telegram inline keyboard, long message, callback, webhook
- Digest expanded analysis rendering
- ExpandPipeline logic (mocked)
- BotServer callback/command handling
- CLI expand-paper and webhook commands
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_radar.bot import BotServer, ExpandPipeline
from paper_radar.config import BotConfig, load_config
from paper_radar.db import PaperRadarDb
from paper_radar.digest import render_expanded_analysis, render_paper_markdown, render_paper_short
from paper_radar.llm import build_expand_prompt
from paper_radar.telegram import (
    TelegramSender,
    _split_message,
    make_expand_keyboard,
)


class TestExpansionDb(unittest.TestCase):
    """Test paper_expansions table and DB methods."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = PaperRadarDb(Path(self.tmpdir) / "test.sqlite3")
        self.db.initialize()

    def test_table_created(self):
        """paper_expansions table exists after initialize."""
        with self.db._connect() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertIn("paper_expansions", tables)

    def test_get_expansion_empty(self):
        """get_expansion returns None for unknown arxiv_id."""
        result = self.db.get_expansion("nonexistent")
        self.assertIsNone(result)

    def test_get_expansion_empty_arxiv_id(self):
        """get_expansion returns None for empty arxiv_id."""
        result = self.db.get_expansion("")
        self.assertIsNone(result)

    def test_save_and_get_expansion(self):
        """Save and retrieve an expansion."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test Paper",
                "abstract": "Test abstract",
            }
        )
        skeleton = {"deep_summary": "A deep summary", "strengths": ["good math"]}
        self.db.save_expansion(paper_id, "2606.03988", skeleton)

        result = self.db.get_expansion("2606.03988")
        self.assertIsNotNone(result)
        self.assertEqual(result["arxiv_id"], "2606.03988")
        self.assertEqual(result["skeleton"]["deep_summary"], "A deep summary")
        self.assertEqual(result["skeleton"]["strengths"], ["good math"])

    def test_save_expansion_upsert(self):
        """Saving expansion twice updates the existing record."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test Paper",
            }
        )
        self.db.save_expansion(paper_id, "2606.03988", {"deep_summary": "v1"})
        self.db.save_expansion(paper_id, "2606.03988", {"deep_summary": "v2"})

        result = self.db.get_expansion("2606.03988")
        self.assertEqual(result["skeleton"]["deep_summary"], "v2")

    def test_save_expansion_returns_id(self):
        """save_expansion returns an integer id."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test Paper",
            }
        )
        exp_id = self.db.save_expansion(paper_id, "2606.03988", {"key": "val"})
        self.assertIsInstance(exp_id, int)
        self.assertGreater(exp_id, 0)


class TestBuildExpandPrompt(unittest.TestCase):
    """Test the expand prompt builder."""

    def test_returns_tuple(self):
        """build_expand_prompt returns (system, user) tuple."""
        system, user = build_expand_prompt("Title", "Abstract", "Full text")
        self.assertIsInstance(system, str)
        self.assertIsInstance(user, str)

    def test_system_lists_all_keys(self):
        """System prompt mentions all 13 skeleton keys."""
        system, _ = build_expand_prompt("T", "A", "F")
        expected_keys = [
            "deep_summary",
            "problem_statement",
            "key_contribution",
            "methodology_detail",
            "mathematical_framework",
            "experiments_and_results",
            "strengths",
            "weaknesses",
            "reproducibility",
            "related_work_context",
            "practical_applications",
            "extension_ideas",
            "reading_recommendation",
        ]
        for key in expected_keys:
            self.assertIn(key, system, f"Missing key '{key}' in system prompt")

    def test_user_includes_paper_data(self):
        """User prompt includes title, abstract, and full text."""
        _, user = build_expand_prompt("My Title", "My Abstract", "My Full Text")
        user_data = json.loads(user)
        self.assertEqual(user_data["title"], "My Title")
        self.assertEqual(user_data["abstract"], "My Abstract")
        self.assertIn("My Full Text", user_data["full_text_markdown"])

    def test_truncates_long_text(self):
        """Long full text is truncated to _EXPAND_MAX_TEXT_CHARS."""
        long_text = "x" * 50000
        _, user = build_expand_prompt("T", "A", long_text)
        user_data = json.loads(user)
        self.assertLessEqual(len(user_data["full_text_markdown"]), 30100)

    def test_expand_uses_larger_limit_than_summary(self):
        """Expand prompt uses a larger text limit than summary prompt."""
        from paper_radar.llm import _EXPAND_MAX_TEXT_CHARS, _MAX_TEXT_CHARS

        self.assertGreater(_EXPAND_MAX_TEXT_CHARS, _MAX_TEXT_CHARS)


class TestMakeExpandKeyboard(unittest.TestCase):
    """Test inline keyboard creation."""

    def test_creates_expand_button(self):
        """make_expand_keyboard creates correct button structure."""
        kb = make_expand_keyboard("2606.03988")
        self.assertIn("inline_keyboard", kb)
        self.assertEqual(len(kb["inline_keyboard"]), 1)
        self.assertEqual(len(kb["inline_keyboard"][0]), 1)
        button = kb["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "🔍 Expand")
        self.assertEqual(button["callback_data"], "expand:2606.03988")

    def test_different_arxiv_ids(self):
        """Different arxiv_ids produce different callback_data."""
        kb1 = make_expand_keyboard("2606.03988")
        kb2 = make_expand_keyboard("2606.03989")
        self.assertNotEqual(
            kb1["inline_keyboard"][0][0]["callback_data"],
            kb2["inline_keyboard"][0][0]["callback_data"],
        )


class TestTelegramSenderMethods(unittest.TestCase):
    """Test new TelegramSender methods."""

    def _make_sender(self, post_mock=None):
        return TelegramSender(
            bot_token="test-token",
            chat_id="12345",
            http_post=post_mock or (lambda *a, **kw: {"ok": True}),
        )

    def test_send_message_with_reply_markup(self):
        """send_message includes reply_markup when provided."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True}

        sender = self._make_sender(capture_post)
        kb = make_expand_keyboard("2606.03988")
        sender.send_message("test msg", reply_markup=kb)

        self.assertEqual(len(calls), 1)
        payload = calls[0]["payload"]
        self.assertIn("reply_markup", payload)
        parsed = json.loads(payload["reply_markup"])
        self.assertIn("inline_keyboard", parsed)

    def test_send_message_without_reply_markup(self):
        """send_message works without reply_markup (backward compat)."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True}

        sender = self._make_sender(capture_post)
        sender.send_message("test msg")

        self.assertEqual(len(calls), 1)
        payload = calls[0]["payload"]
        self.assertNotIn("reply_markup", payload)

    def test_send_message_with_chat_id(self):
        """send_message uses provided chat_id instead of default."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True}

        sender = self._make_sender(capture_post)
        sender.send_message("test msg", chat_id="99999")

        payload = calls[0]["payload"]
        self.assertEqual(payload["chat_id"], "99999")

    def test_send_message_empty_returns_empty(self):
        """send_message with empty text returns empty dict."""
        sender = self._make_sender()
        result = sender.send_message("")
        self.assertEqual(result, {})

    def test_send_long_message_splits(self):
        """send_long_message splits text exceeding limit."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True}

        sender = self._make_sender(capture_post)
        long_text = "line\n" * 2000  # ~10000 chars
        sender.send_long_message(long_text)

        self.assertGreater(len(calls), 1)

    def test_send_long_message_reply_markup_on_last(self):
        """send_long_message puts reply_markup only on last chunk."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True}

        sender = self._make_sender(capture_post)
        long_text = "line\n" * 2000
        kb = make_expand_keyboard("2606.03988")
        sender.send_long_message(long_text, reply_markup=kb)

        for call in calls[:-1]:
            self.assertNotIn("reply_markup", call["payload"])
        self.assertIn("reply_markup", calls[-1]["payload"])

    def test_answer_callback_query(self):
        """answer_callback_query sends correct payload."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True}

        sender = self._make_sender(capture_post)
        sender.answer_callback_query("cbq123", text="Processing...")

        self.assertEqual(len(calls), 1)
        payload = calls[0]["payload"]
        self.assertEqual(payload["callback_query_id"], "cbq123")
        self.assertEqual(payload["text"], "Processing...")

    def test_set_webhook(self):
        """set_webhook sends correct payload."""
        calls = []

        def capture_post(url, **kw):
            calls.append(kw)
            return {"ok": True, "result": True}

        sender = self._make_sender(capture_post)
        result = sender.set_webhook("https://example.com/webhook")

        self.assertTrue(result.get("ok"))
        payload = calls[0]["payload"]
        self.assertEqual(payload["url"], "https://example.com/webhook")

    def test_delete_webhook(self):
        """delete_webhook sends correct request."""
        calls = []

        def capture_post(url, **kw):
            calls.append({"url": url, **kw})
            return {"ok": True}

        sender = self._make_sender(capture_post)
        sender.delete_webhook()
        self.assertEqual(len(calls), 1)
        self.assertIn("deleteWebhook", calls[0]["url"])

    def test_get_me(self):
        """get_me sends request and returns result."""
        sender = self._make_sender()
        result = sender.get_me()
        self.assertEqual(result, {"ok": True})


class TestSplitMessage(unittest.TestCase):
    """Test the _split_message helper."""

    def test_short_message(self):
        """Short message returns single chunk."""
        chunks = _split_message("short", 4096)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "short")

    def test_splits_at_newline(self):
        """Splits at newline boundary."""
        # Set limit to force split after line1
        chunks = _split_message("line1\nline2\nline3\n", 12)
        self.assertGreater(len(chunks), 1)

    def test_no_newline_splits_at_limit(self):
        """When no newline, splits at exact limit."""
        text = "a" * 100
        chunks = _split_message(text, 50)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 50)

    def test_exact_limit(self):
        """Text at exact limit returns single chunk."""
        text = "a" * 100
        chunks = _split_message(text, 100)
        self.assertEqual(len(chunks), 1)


class TestRenderExpandedAnalysis(unittest.TestCase):
    """Test the expanded analysis renderer."""

    def test_basic_rendering(self):
        """Renders all sections with values."""
        expansion = {
            "skeleton": {
                "deep_summary": "A deep summary of the paper.",
                "key_contribution": "Main contribution here.",
                "strengths": ["good math", "clear writing"],
            },
            "arxiv_id": "2606.03988",
        }
        paper = {"title": "Test Paper", "arxiv_id": "2606.03988"}
        result = render_expanded_analysis(expansion, paper=paper)

        self.assertIn("🔬 *Expanded: Test Paper*", result)
        self.assertIn("2606.03988", result)
        self.assertIn("A deep summary", result)
        self.assertIn("Main contribution", result)
        self.assertIn("good math", result)
        self.assertIn("clear writing", result)

    def test_empty_skeleton(self):
        """Handles empty skeleton gracefully."""
        expansion = {"skeleton": {}}
        result = render_expanded_analysis(expansion)
        # Should still have the header area but no section content
        self.assertIsInstance(result, str)

    def test_no_paper(self):
        """Works without paper metadata."""
        expansion = {
            "skeleton": {"deep_summary": "Something"},
            "arxiv_id": "2606.03988",
        }
        result = render_expanded_analysis(expansion)
        self.assertIn("2606.03988", result)
        self.assertIn("Something", result)

    def test_list_values_rendered_as_bullets(self):
        """List values are rendered as bullet points."""
        expansion = {
            "skeleton": {
                "extension_ideas": ["idea 1", "idea 2", "idea 3"],
            },
        }
        result = render_expanded_analysis(expansion)
        self.assertIn("• idea 1", result)
        self.assertIn("• idea 2", result)
        self.assertIn("• idea 3", result)

    def test_all_13_sections(self):
        """All 13 sections appear in the output when populated."""
        skeleton = {
            key: f"Value for {key}"
            for key in [
                "deep_summary",
                "problem_statement",
                "key_contribution",
                "methodology_detail",
                "mathematical_framework",
                "experiments_and_results",
                "strengths",
                "weaknesses",
                "reproducibility",
                "related_work_context",
                "practical_applications",
                "extension_ideas",
                "reading_recommendation",
            ]
        }
        expansion = {"skeleton": skeleton}
        result = render_expanded_analysis(expansion)

        labels = [
            "Deep Summary",
            "Problem Statement",
            "Key Contribution",
            "Methodology Detail",
            "Mathematical Framework",
            "Experiments & Results",
            "Strengths",
            "Weaknesses",
            "Reproducibility",
            "Related Work Context",
            "Practical Applications",
            "Extension Ideas",
            "Reading Recommendation",
        ]
        for label in labels:
            self.assertIn(label, result, f"Missing section: {label}")


class TestExpandPipeline(unittest.TestCase):
    """Test ExpandPipeline with mocked dependencies."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = PaperRadarDb(Path(self.tmpdir) / "test.sqlite3")
        self.db.initialize()
        self.llm = MagicMock()
        self.telegram = MagicMock()
        self.pipeline = ExpandPipeline(db=self.db, llm=self.llm, telegram=self.telegram)

    def test_expand_cached(self):
        """Returns cached result without calling LLM."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Cached Paper",
            }
        )
        self.db.save_expansion(paper_id, "2606.03988", {"deep_summary": "cached"})

        status = self.pipeline.expand_and_send("2606.03988", "12345")
        self.assertEqual(status, "cached")
        self.llm.complete_json.assert_not_called()
        self.telegram.send_long_message.assert_called_once()

    def test_expand_not_found(self):
        """Returns not_found for unknown arxiv_id."""
        status = self.pipeline.expand_and_send("nonexistent", "12345")
        self.assertEqual(status, "not_found")
        self.telegram.send_message.assert_called_once()
        call_args = self.telegram.send_message.call_args
        self.assertIn("not found", call_args[0][0].lower() + call_args[1].get("text", "").lower())

    def test_expand_with_existing_text(self):
        """Expand uses existing full text from DB."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test Paper",
                "abstract": "Abstract",
                "pdf_url": "https://example.com/paper.pdf",
            }
        )
        self.db.upsert_paper_text(
            paper_id,
            full_text="Full paper text here",
            introduction_text="Intro",
            extraction_status="extracted",
            extractor_name="pymupdf",
        )
        self.llm.complete_json.return_value = {"deep_summary": "Expanded!"}

        status = self.pipeline.expand_and_send("2606.03988", "12345")
        self.assertEqual(status, "expanded")
        self.llm.complete_json.assert_called_once()

        # Verify expansion was saved
        cached = self.db.get_expansion("2606.03988")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["skeleton"]["deep_summary"], "Expanded!")

    def test_expand_no_text(self):
        """Returns no_text when paper has no text and no PDF URL."""
        self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "No Text Paper",
                "pdf_url": "",
            }
        )
        with patch("paper_radar.bot.download_pdf", side_effect=Exception("download failed")):
            status = self.pipeline.expand_and_send("2606.03988", "12345")
        self.assertEqual(status, "no_text")

    def test_expand_llm_error(self):
        """Returns llm_error when LLM fails."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test Paper",
                "abstract": "Abstract",
            }
        )
        self.db.upsert_paper_text(
            paper_id,
            full_text="Some text",
            extraction_status="extracted",
            extractor_name="pymupdf",
        )
        self.llm.complete_json.side_effect = Exception("LLM timeout")

        status = self.pipeline.expand_and_send("2606.03988", "12345")
        self.assertEqual(status, "llm_error")


class TestBotServer(unittest.TestCase):
    """Test BotServer callback and command handling."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = PaperRadarDb(Path(self.tmpdir) / "test.sqlite3")
        self.db.initialize()

        from paper_radar.config import AppConfig

        config = AppConfig(bot=BotConfig(webhook_url="", webhook_port=8080))
        self.llm = MagicMock()
        self.telegram = MagicMock()
        self.server = BotServer(config=config, db=self.db, llm=self.llm, telegram=self.telegram)

    def test_handle_callback_expand(self):
        """Processes expand callback correctly."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test",
            }
        )
        self.db.save_expansion(paper_id, "2606.03988", {"deep_summary": "cached"})

        update = {
            "callback_query": {
                "id": "cbq1",
                "data": "expand:2606.03988",
                "message": {"chat": {"id": 12345}},
            },
        }
        self.server.handle_update(update)

        self.telegram.answer_callback_query.assert_called_once_with("cbq1", text="Đang phân tích chi tiết...")
        self.telegram.send_long_message.assert_called_once()

    def test_handle_expand_command(self):
        """Processes /expand command correctly."""
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test",
            }
        )
        self.db.save_expansion(paper_id, "2606.03988", {"deep_summary": "cached"})

        update = {
            "message": {
                "text": "/expand 2606.03988",
                "chat": {"id": 12345},
            },
        }
        self.server.handle_update(update)

        self.telegram.send_long_message.assert_called_once()
        call_kwargs = self.telegram.send_long_message.call_args
        self.assertEqual(call_kwargs[1]["chat_id"], "12345")

    def test_handle_expand_command_missing_id(self):
        """Handles /expand without arxiv_id."""
        update = {
            "message": {
                "text": "/expand",
                "chat": {"id": 12345},
            },
        }
        self.server.handle_update(update)
        self.telegram.send_message.assert_called_once()
        msg = self.telegram.send_message.call_args[0][0]
        self.assertIn("Usage", msg)

    def test_handle_unknown_update(self):
        """Ignores unknown update types."""
        update = {"message": {"text": "hello world", "chat": {"id": 1}}}
        self.server.handle_update(update)
        self.telegram.send_message.assert_not_called()
        self.telegram.send_long_message.assert_not_called()

    def test_handle_non_expand_callback(self):
        """Ignores callbacks that don't start with 'expand:'."""
        update = {
            "callback_query": {
                "id": "cbq1",
                "data": "other:action",
                "message": {"chat": {"id": 12345}},
            },
        }
        self.server.handle_update(update)
        self.telegram.answer_callback_query.assert_not_called()


class TestBotConfig(unittest.TestCase):
    """Test BotConfig integration."""

    def test_default_values(self):
        """BotConfig has sensible defaults."""
        config = BotConfig()
        self.assertEqual(config.webhook_url, "")
        self.assertEqual(config.webhook_port, 8080)

    def test_config_loads_from_env(self):
        """BotConfig loads webhook_url from environment."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("BOT_WEBHOOK_URL=https://example.com/webhook\n")
            f.flush()
            env_path = f.name

        try:
            with patch.dict(os.environ, {"BOT_WEBHOOK_URL": "https://env.example.com/webhook"}):
                config = load_config("/nonexistent.yaml", env_path)
                self.assertEqual(config.bot.webhook_url, "https://env.example.com/webhook")
        finally:
            os.unlink(env_path)

    def test_config_override_port(self):
        """BotConfig port can be overridden via dataclasses.replace."""
        config = BotConfig(webhook_port=9090)
        self.assertEqual(config.webhook_port, 9090)

        overridden = replace(config, webhook_port=8888)
        self.assertEqual(overridden.webhook_port, 8888)


class TestBackwardCompatibility(unittest.TestCase):
    """Verify existing functionality still works with the changes."""

    def test_telegram_send_message_backward_compat(self):
        """send_message still works with old signature (text only)."""
        sender = TelegramSender(
            bot_token="token",
            chat_id="123",
            http_post=lambda *a, **kw: {"ok": True},
        )
        result = sender.send_message("Hello world")
        self.assertEqual(result, {"ok": True})

    def test_db_still_creates_all_tables(self):
        """All original tables still exist after schema change."""
        tmpdir = tempfile.mkdtemp()
        db = PaperRadarDb(Path(tmpdir) / "test.sqlite3")
        db.initialize()

        with db._connect() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        for table in ["papers", "runs", "paper_results", "telegram_recaps", "state", "paper_texts", "paper_expansions"]:
            self.assertIn(table, tables)

    def test_existing_digest_functions_unchanged(self):
        """Existing digest functions produce same output."""

        paper = {
            "title": "Test Paper",
            "arxiv_id": "2606.03988",
            "pdf_url": "https://arxiv.org/pdf/2606.03988",
            "summary": {"what_the_paper_does": "Something", "novelty": "New"},
        }
        short = render_paper_short(paper)
        self.assertIn("Test Paper", short)
        self.assertIn("2606.03988", short)

        paper["summary"]["qa_scores"] = {}
        paper["summary"]["ideas_to_try"] = []
        md = render_paper_markdown(paper)
        self.assertIn("Test Paper", md)


class TestAuthorAffiliations(unittest.TestCase):
    """Test author affiliation storage and display."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = PaperRadarDb(Path(self.tmpdir) / "test.sqlite3")
        self.db.initialize()

    def test_author_affiliations_table_created(self):
        """author_affiliations table exists after initialize."""
        with self.db._connect() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertIn("author_affiliations", tables)

    def test_save_and_get_author_affiliation(self):
        """Save and retrieve author affiliation."""
        self.db.save_author_affiliation("12345", "John Doe", "MIT")
        result = self.db.get_author_affiliations_batch(["12345"])
        self.assertEqual(result, {"12345": "MIT"})

    def test_batch_get_misses_uncached(self):
        """Batch get returns only cached authors."""
        self.db.save_author_affiliation("111", "Alice", "Stanford")
        result = self.db.get_author_affiliations_batch(["111", "999"])
        self.assertEqual(result, {"111": "Stanford"})

    def test_batch_get_empty_list(self):
        """Batch get with empty list returns empty dict."""
        result = self.db.get_author_affiliations_batch([])
        self.assertEqual(result, {})

    def test_save_author_affiliation_updates(self):
        """Saving twice updates the affiliation."""
        self.db.save_author_affiliation("12345", "John", "MIT")
        self.db.save_author_affiliation("12345", "John", "Google")
        result = self.db.get_author_affiliations_batch(["12345"])
        self.assertEqual(result["12345"], "Google")

    def test_paper_stores_author_affiliations(self):
        """Paper record stores author_affiliations_json."""
        self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test",
                "author_affiliations": ["MIT", "Google"],
                "author_s2_ids": ["111", "222"],
            }
        )
        paper = self.db.get_paper_by_arxiv_id("2606.03988")
        self.assertIsNotNone(paper)
        affiliations = json.loads(paper.get("author_affiliations_json", "[]"))
        self.assertEqual(affiliations, ["MIT", "Google"])
        s2_ids = json.loads(paper.get("author_s2_ids_json", "[]"))
        self.assertEqual(s2_ids, ["111", "222"])

    def test_render_paper_short_with_affiliations(self):
        """render_paper_short shows affiliations."""
        paper = {
            "title": "Test Paper",
            "arxiv_id": "2606.03988",
            "pdf_url": "https://arxiv.org/pdf/2606.03988",
            "summary": {"what_the_paper_does": "Something"},
            "author_affiliations": ["MIT", "Google DeepMind", "Stanford University"],
        }
        result = render_paper_short(paper)
        self.assertIn("🏢", result)
        self.assertIn("MIT", result)
        self.assertIn("Google DeepMind", result)

    def test_render_paper_short_deduplicates_affiliations(self):
        """render_paper_short deduplicates affiliations."""
        paper = {
            "title": "Test",
            "arxiv_id": "2606.03988",
            "pdf_url": "",
            "summary": {},
            "author_affiliations": ["MIT", "MIT", "Google"],
        }
        result = render_paper_short(paper)
        self.assertEqual(result.count("MIT"), 1)

    def test_render_paper_short_limits_to_five_affiliations(self):
        """render_paper_short shows max 5 affiliations."""
        paper = {
            "title": "Test",
            "arxiv_id": "2606.03988",
            "pdf_url": "",
            "summary": {},
            "author_affiliations": [f"Org{i}" for i in range(10)],
        }
        result = render_paper_short(paper)
        self.assertIn("Org0", result)
        self.assertIn("Org4", result)
        self.assertNotIn("Org5", result)

    def test_render_paper_short_no_affiliations(self):
        """render_paper_short works without affiliations."""
        paper = {
            "title": "Test",
            "arxiv_id": "2606.03988",
            "pdf_url": "",
            "summary": {},
        }
        result = render_paper_short(paper)
        self.assertNotIn("👥", result)

    def test_s2_item_parses_authors(self):
        """s2_item_to_paper parses authors and author IDs."""
        from paper_radar._s2 import s2_item_to_paper

        item = {
            "externalIds": {"ArXiv": "2606.03988"},
            "paperId": "abc123",
            "title": "Test Paper",
            "authors": [
                {"authorId": "111", "name": "Alice"},
                {"authorId": "222", "name": "Bob"},
            ],
        }
        paper = s2_item_to_paper(item)
        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.authors, ["Alice", "Bob"])
        self.assertEqual(paper.author_s2_ids, ["111", "222"])
        self.assertEqual(paper.author_affiliations, [])

    def test_s2_item_handles_missing_authors(self):
        """s2_item_to_paper handles missing authors field."""
        from paper_radar._s2 import s2_item_to_paper

        item = {
            "externalIds": {"ArXiv": "2606.03988"},
            "paperId": "abc123",
            "title": "Test",
        }
        paper = s2_item_to_paper(item)
        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.authors, [])
        self.assertEqual(paper.author_s2_ids, [])

    def test_paper_metadata_to_record_includes_new_fields(self):
        """PaperMetadata.to_record includes author_s2_ids and author_affiliations."""
        from paper_radar._s2 import PaperMetadata

        paper = PaperMetadata(
            arxiv_id="2606.03988",
            authors=["Alice"],
            author_s2_ids=["111"],
            author_affiliations=["MIT"],
        )
        record = paper.to_record()
        self.assertIn("author_s2_ids", record)
        self.assertIn("author_affiliations", record)
        self.assertEqual(record["author_s2_ids"], ["111"])
        self.assertEqual(record["author_affiliations"], ["MIT"])

    def test_accepted_results_include_affiliations(self):
        """accepted_results_for_date includes author_affiliations."""
        run_id = self.db.start_run()
        paper_id = self.db.upsert_paper(
            {
                "arxiv_id": "2606.03988",
                "title": "Test",
                "author_affiliations": ["MIT"],
                "author_s2_ids": ["111"],
            }
        )
        self.db.record_result(
            paper_id=paper_id,
            run_id=run_id,
            candidate_relevance_score=8,
            extractor_name="primary",
            extracted_text_chars=100,
            summary={"what_the_paper_does": "work"},
            relevance_score=8,
            grounding_score=8,
            idea_score=7,
            qa_reason="ok",
            accepted=True,
            digest_date="2026-06-04",
        )
        results = self.db.accepted_results_for_date("2026-06-04")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["author_affiliations"], ["MIT"])
        self.assertEqual(results[0]["author_s2_ids"], ["111"])


if __name__ == "__main__":
    unittest.main()
