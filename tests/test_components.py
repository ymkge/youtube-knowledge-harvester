"""Unit tests for extractor, summarizer, and exporter modules."""

import io
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from core.exporter import MarkdownExporter, generate_filename, sanitize_filename
from core.extractor import (
    SubtitleSnippet,
    VideoMetadata,
    VideoTranscriptData,
    fetch_video_upload_date,
    normalize_channel_url,
)
from core.summarizer import (
    build_prompt,
    clean_markdown_output,
    format_published_date,
)


class TestExtractor(unittest.TestCase):
    def test_normalize_channel_url(self):
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@test"),
            "https://www.youtube.com/@test/videos",
        )
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@test/videos"),
            "https://www.youtube.com/@test/videos",
        )
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@test/"),
            "https://www.youtube.com/@test/videos",
        )

    def test_transcript_formatting(self):
        meta = VideoMetadata(
            video_id="abc123xyz",
            title="Test Video",
            url="https://www.youtube.com/watch?v=abc123xyz",
        )
        subtitles = [
            SubtitleSnippet(start=10.5, duration=2.0, text="Hello"),
            SubtitleSnippet(start=75.0, duration=3.0, text="World"),
        ]
        data = VideoTranscriptData(
            metadata=meta,
            subtitles=subtitles,
            language="ja",
            is_generated=False,
        )
        formatted = data.formatted_transcript_text()
        self.assertIn("[00:10] Hello", formatted)
        self.assertIn("[01:15] World", formatted)

    @patch("core.extractor.yt_dlp.YoutubeDL")
    def test_fetch_video_upload_date(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        # 1. Success case
        mock_ydl.extract_info.return_value = {"upload_date": "20240501"}
        date = fetch_video_upload_date("test_id")
        self.assertEqual(date, "20240501")

        # 2. None case
        mock_ydl.extract_info.return_value = {}
        date_none = fetch_video_upload_date("test_id")
        self.assertIsNone(date_none)

        # 3. Exception case
        mock_ydl.extract_info.side_effect = Exception("Network error")
        date_err = fetch_video_upload_date("test_id")
        self.assertIsNone(date_err)


class TestSummarizer(unittest.TestCase):
    def test_format_published_date(self):
        self.assertEqual(format_published_date("20240115"), "2024-01-15")
        self.assertEqual(format_published_date("2024-01-15"), "2024-01-15")
        self.assertEqual(format_published_date(None), "Unknown")

    def test_clean_markdown_output(self):
        raw = "```markdown\n---\ntitle: test\n---\n# Test\n```"
        cleaned = clean_markdown_output(raw)
        self.assertEqual(cleaned, "---\ntitle: test\n---\n# Test")

        raw_no_tag = "```\n---\ntitle: test\n---\n```"
        self.assertEqual(clean_markdown_output(raw_no_tag), "---\ntitle: test\n---")

        clean_already = "---\ntitle: test\n---"
        self.assertEqual(clean_markdown_output(clean_already), "---\ntitle: test\n---")

    def test_build_prompt(self):
        meta = VideoMetadata(
            video_id="abc123xyz",
            title="Test Video",
            url="https://www.youtube.com/watch?v=abc123xyz",
            channel="Tech Channel",
            upload_date="20240501",
        )
        subtitles = [SubtitleSnippet(start=120.0, duration=5.0, text="Introduction to AI")]
        data = VideoTranscriptData(
            metadata=meta,
            subtitles=subtitles,
            language="ja",
            is_generated=False,
        )
        prompt = build_prompt(data)
        self.assertIn("abc123xyz", prompt)
        self.assertIn("Test Video", prompt)
        self.assertIn("[02:00] Introduction to AI", prompt)
        self.assertIn("summary:", prompt)
        self.assertIn("💡 要点 (TL;DR)", prompt)

    @patch("core.summarizer.genai.Client")
    def test_summarize_audio(self, mock_client_cls):
        from core.summarizer import GeminiSummarizer

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_file = MagicMock()
        mock_file.name = "files/test_audio_123"
        mock_file.state = "ACTIVE"
        mock_client.files.upload.return_value = mock_file

        mock_response = MagicMock()
        mock_response.text = "---\ntitle: Audio Title\n---\n# Audio Title"
        mock_client.models.generate_content.return_value = mock_response

        summarizer = GeminiSummarizer(api_key="fake-key")
        meta = VideoMetadata(
            video_id="vid123",
            title="Audio Title",
            url="https://www.youtube.com/watch?v=vid123",
        )

        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".webm") as tmp:
            result = summarizer.summarize_audio(audio_path=tmp.name, metadata=meta)

        self.assertIn("Audio Title", result)
        mock_client.files.upload.assert_called_once()
        # Verify that UploadFileConfig with mime_type='audio/webm' was passed
        _, kwargs = mock_client.files.upload.call_args
        self.assertIn("config", kwargs)
        self.assertEqual(kwargs["config"].mime_type, "audio/webm")
        mock_client.files.delete.assert_called_once_with(name="files/test_audio_123")

    def test_default_model_is_lite(self):
        from core.summarizer import AVAILABLE_MODELS, DEFAULT_MODEL
        self.assertEqual(DEFAULT_MODEL, "gemini-flash-lite-latest")
        self.assertEqual(AVAILABLE_MODELS[0], "gemini-flash-lite-latest")

    def test_quota_exhausted_detection(self):
        from core.summarizer import (
            is_quota_exhausted_error,
            is_transient_error,
        )
        daily_quota_error = Exception(
            "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
            "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, "
            "model: gemini-3.8-flash. Please retry in 10h38m50s. "
            "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        )
        transient_429_error = Exception("429 RESOURCE_EXHAUSTED: Rate limit exceeded. Please wait a moment.")

        self.assertTrue(is_quota_exhausted_error(daily_quota_error))
        self.assertFalse(is_quota_exhausted_error(transient_429_error))

        # Daily quota error should NOT be treated as transient (should not retry)
        self.assertFalse(is_transient_error(daily_quota_error))
        # Transient 429 should be treated as transient
        self.assertTrue(is_transient_error(transient_429_error))

    @patch("core.summarizer.genai.Client")
    def test_summarize_quota_exhaustion_raises_immediately(self, mock_client_cls):
        from core.summarizer import GeminiQuotaExhaustedException, GeminiSummarizer

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception(
            "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
            "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20"
        )

        summarizer = GeminiSummarizer(api_key="fake-key")
        meta = VideoMetadata(
            video_id="abc123xyz",
            title="Test Video",
            url="https://www.youtube.com/watch?v=abc123xyz",
        )
        data = VideoTranscriptData(
            metadata=meta,
            subtitles=[SubtitleSnippet(start=0.0, duration=1.0, text="test")],
            language="ja",
            is_generated=False,
        )

        retry_count = 0
        def on_retry(att, wait, err):
            nonlocal retry_count
            retry_count += 1

        with self.assertRaises(GeminiQuotaExhaustedException):
            summarizer.summarize(data, max_retries=3, on_retry=on_retry)

        # Should raise immediately without transient retries
        self.assertEqual(retry_count, 0)
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    def test_get_audio_mime_type(self):
        from core.summarizer import get_audio_mime_type
        self.assertEqual(get_audio_mime_type("test.webm"), "audio/webm")
        self.assertEqual(get_audio_mime_type("test.m4a"), "audio/mp4")
        self.assertEqual(get_audio_mime_type("test.mp3"), "audio/mp3")
        self.assertEqual(get_audio_mime_type("test.ogg"), "audio/ogg")
        self.assertEqual(get_audio_mime_type("test.unknown"), "audio/webm")


class TestExporter(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("valid_name"), "valid_name")
        self.assertEqual(sanitize_filename('invalid:name/test"'), "invalid_name_test_")

    def test_generate_filename(self):
        meta = VideoMetadata(
            video_id="dQw4w9WgXcQ",
            title="Never Gonna Give You Up",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            upload_date="20091025",
        )
        self.assertEqual(generate_filename(meta, prefix_date=True), "20091025_dQw4w9WgXcQ.md")
        self.assertEqual(generate_filename(meta, prefix_date=False), "dQw4w9WgXcQ.md")

    def test_create_zip_archive(self):
        files = {
            "test1.md": "# Test 1 Content",
            "test2.md": "# Test 2 Content",
        }
        zip_bytes = MarkdownExporter.create_zip_archive(files)
        self.assertIsInstance(zip_bytes, bytes)

        # Verify ZIP content
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            self.assertEqual(set(zf.namelist()), {"test1.md", "test2.md"})
            self.assertEqual(zf.read("test1.md").decode("utf-8"), "# Test 1 Content")


if __name__ == "__main__":
    unittest.main()
