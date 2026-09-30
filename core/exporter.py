"""Markdown file persistence and ZIP export module."""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from core.extractor import VideoMetadata

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames across operating systems."""
    # Replace dangerous characters with underscore
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name)
    # Strip leading/trailing spaces and dots
    return cleaned.strip(". ")


def generate_filename(metadata: VideoMetadata, prefix_date: bool = True) -> str:
    """Generate Markdown filename for a video.

    Format: {upload_date}_{video_id}.md or {video_id}.md
    """
    safe_video_id = sanitize_filename(metadata.video_id)
    if prefix_date and metadata.upload_date:
        safe_date = sanitize_filename(metadata.upload_date)
        return f"{safe_date}_{safe_video_id}.md"
    return f"{safe_video_id}.md"


class MarkdownExporter:
    """Handles saving markdown files and building zip archives."""

    def __init__(self, output_dir: str | Path = "./output/knowledge"):
        """Initialize exporter with target directory.

        Args:
            output_dir: Directory where markdown files will be saved.
        """
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_markdown(self, filename: str, content: str) -> Path:
        """Save a single markdown content to the output directory.

        Args:
            filename: Target file name (e.g. '20240101_xxxx.md').
            content: Markdown content string.

        Returns:
            Path of the saved file.
        """
        file_path = self.output_dir / filename
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved knowledge markdown to {file_path}")
        return file_path

    @staticmethod
    def create_zip_archive(files: Dict[str, str]) -> bytes:
        """Create an in-memory ZIP archive from a dictionary of filename -> content.

        Args:
            files: Dictionary mapping filename to markdown text.

        Returns:
            ZIP file contents as bytes.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for filename, content in files.items():
                zf.writestr(filename, content.encode("utf-8"))
        buf.seek(0)
        return buf.getvalue()

    def create_zip_from_dir(self, pattern: str = "*.md") -> bytes:
        """Create an in-memory ZIP archive from all matching files in output_dir.

        Args:
            pattern: Glob pattern for matching files.

        Returns:
            ZIP file contents as bytes.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in self.output_dir.glob(pattern):
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.name)
        buf.seek(0)
        return buf.getvalue()
