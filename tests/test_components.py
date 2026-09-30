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
