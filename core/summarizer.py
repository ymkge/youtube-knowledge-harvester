"""Gemini API summarization module for RAG-oriented structured Markdown."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional
from google import genai
from google.genai import types
from core.extractor import VideoTranscriptData

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
AVAILABLE_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]

RETRYABLE_PATTERNS = [
    "429",
    "resource_exhausted",
    "quotaexceeded",
    "503",
    "unavailable",
    "high demand",
    "serviceunavailable",
    "500",
    "502",
    "504",
    "bad gateway",
    "gateway timeout",
    "deadlineexceeded",
    "timeout",
    "failed_precondition",
    "active state",
]


def is_transient_error(error: Any) -> bool:
    """Check if the error is temporary (rate limit 429, server overload 503, timeout)."""
    err_str = str(error).lower()
    return any(p in err_str for p in RETRYABLE_PATTERNS)


def format_published_date(date_str: Optional[str]) -> str:
    """Format YYYYMMDD string to YYYY-MM-DD."""
    if not date_str:
        return "Unknown"
    date_str = date_str.strip()
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def clean_markdown_output(text: str) -> str:
    """Strip markdown code fence wrapper if present."""
    text = text.strip()
    # Match ```markdown ... ``` or ``` ... ```
    pattern = r"^```(?:markdown)?\s*\n(.*?)\n```$"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def build_prompt(transcript_data: VideoTranscriptData) -> str:
    """Build structured prompt for Gemini model."""
    meta = transcript_data.metadata
    published_at = format_published_date(meta.upload_date)
    timestamped_transcript = transcript_data.formatted_transcript_text()

    prompt = f"""あなたはAIエージェントおよびRAG（Retrieval-Augmented Generation）システムのための高品質なナレッジ作成専門家です。
以下のYouTube動画のメタデータとタイムスタンプ付き字幕テキストを解析し、後続のAIエージェントが正確かつ迅速に情報を参照・引用できる構造化Markdown（.md）を作成してください。

### 対象動画メタデータ:
- video_id: {meta.video_id}
- title: {meta.title}
- channel: {meta.channel}
- source_url: {meta.url}
- published_at: {published_at}

### タイムスタンプ付き字幕テキスト:
{timestamped_transcript}

---

### 出力フォーマット要件（厳格遵守）:
必ず以下の構造のみを出力してください。挨拶文や前置き、解説、全体のバッククォート囲み（```markdown など）は一切含めず、先頭行の「---」から直接出力してください。

---
title: "{meta.title.replace('"', "'")}"
video_id: "{meta.video_id}"
channel: "{meta.channel.replace('"', "'")}"
source_url: "{meta.url}"
published_at: "{published_at}"
tags:
  - "タグ1"
  - "タグ2"
  - "タグ3"
summary: "動画全体の要約を150字程度で簡潔かつ具体的に記述してください。"
---

# {meta.title}

## 💡 要点 (TL;DR)
- 要点1（本質的・具体的な内容）
- 要点2
- 要点3（3〜5項目）

## 📖 トピック別詳細

### [MM:SS] トピック見出し1
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v={meta.video_id}&t=開始秒s)

トピックの内容を詳細にまとめます。
- AIエージェントが参照・再利用しやすいよう、単なる箇条書きだけでなく、重要な概念、具体的な手順、Tips、コマンドやコード例（あれば）、注意点などを明瞭に構造化してください。
- 該当箇所へのリンクURL末尾の「t=開始秒s」は、該当セクションの開始秒数（例: 03:15 なら t=195s）を正しく計算して記載してください。

### [MM:SS] トピック見出し2
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v={meta.video_id}&t=開始秒s)

...（動画全体のトピックごとにセクションを分割して作成）

### 指針:
1. 日本語で高品質に出力してください（元の字幕が英語の場合でも日本語に分かりやすく翻訳・要約してください）。
2. 事実に基づき、ハルシネーション（字幕に含まれない推測の断定）を避けてください。
3. トピック別詳細は、動画の主要な展開を漏れなく網羅してください。
"""
    return prompt


class GeminiSummarizer:
    """Summarizer using google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the Gemini client.

        Args:
            api_key: Gemini API Key. If None, reads from GEMINI_API_KEY environment variable.
            model: Model name. If None, reads from GEMINI_MODEL or defaults to gemini-flash-latest.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini APIキーが設定されていません。.env ファイルまたは引数で GEMINI_API_KEY を設定してください。"
            )

        self.model_name = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self.client = genai.Client(api_key=self.api_key)

    def summarize(
        self,
        transcript_data: VideoTranscriptData,
        max_retries: int = 3,
        initial_backoff: float = 10.0,
        on_retry: Optional[Any] = None,
    ) -> str:
        """Generate structured markdown from video transcript with automatic retry on rate limits.

        Args:
            transcript_data: VideoTranscriptData containing metadata and subtitles.
            max_retries: Maximum retry attempts on 429/quota errors.
            initial_backoff: Initial wait time in seconds before retry.
            on_retry: Optional callback function(attempt, wait_sec, error_str) for logging/UI.

        Returns:
            Structured Markdown string.
        """
        import time

        prompt = build_prompt(transcript_data)
        current_model = self.model_name

        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                    ),
                )
                if not response or not response.text:
                    raise RuntimeError("Gemini APIから空の応答が返されました。")

                markdown_text = clean_markdown_output(response.text)

                if not markdown_text.startswith("---"):
                    logger.warning(
                        f"Generated markdown for {transcript_data.metadata.video_id} does not start with YAML frontmatter."
                    )

                return markdown_text

            except Exception as e:
                err_str = str(e)
                if is_transient_error(e) and attempt < max_retries:
                    wait_sec = initial_backoff * (2 ** (attempt - 1))

                    # If 503 high demand on flash-latest, fallback to flash-lite for next attempt
                    if any(p in err_str.lower() for p in ["503", "unavailable", "high demand"]):
                        if current_model == "gemini-flash-latest":
                            current_model = "gemini-flash-lite-latest"
                            logger.info(
                                f"Switching to fallback model '{current_model}' due to high demand on Gemini API."
                            )

                    logger.warning(
                        f"Transient error on {transcript_data.metadata.video_id}: {e}. "
                        f"Retrying with '{current_model}' in {wait_sec}s (attempt {attempt}/{max_retries})..."
                    )
                    if on_retry:
                        try:
                            on_retry(attempt, wait_sec, err_str)
                        except Exception:
                            pass
                    time.sleep(wait_sec)
                    continue

                logger.error(f"Gemini API call failed for video {transcript_data.metadata.video_id}: {e}")
                raise RuntimeError(f"Gemini APIによる要約生成に失敗しました: {e}") from e

    def summarize_audio(
        self,
        audio_path: Any,
        metadata: Any,
        max_retries: int = 3,
        initial_backoff: float = 10.0,
        on_retry: Optional[Any] = None,
    ) -> str:
        """Generate structured markdown directly from audio file using Gemini Multimodal API.

        Args:
            audio_path: Path to the local audio file.
            metadata: VideoMetadata object.
            max_retries: Maximum retry attempts on rate limits.
            initial_backoff: Initial wait time in seconds before retry.
            on_retry: Optional callback function.

        Returns:
            Structured Markdown string.
        """
        import time
        from pathlib import Path

        audio_path = Path(audio_path)
        published_at = format_published_date(metadata.upload_date)

        audio_prompt = f"""あなたはAIエージェントおよびRAGシステムのための高品質なナレッジ作成専門家です。
提供されたYouTube動画の音声を詳細に聴き取り・解析し、後続のAIエージェントが正確に参照・引用できる構造化Markdown（.md）を作成してください。

### 対象動画メタデータ:
- video_id: {metadata.video_id}
- title: {metadata.title}
- channel: {metadata.channel}
- source_url: {metadata.url}
- published_at: {published_at}

---

### 出力フォーマット要件（厳格遵守）:
必ず以下の構造のみを出力してください。挨拶文や前置き、解説、全体のバッククォート囲み（```markdown など）は一切含めず、先頭行の「---」から直接出力してください。

---
title: "{metadata.title.replace('"', "'")}"
video_id: "{metadata.video_id}"
channel: "{metadata.channel.replace('"', "'")}"
source_url: "{metadata.url}"
published_at: "{published_at}"
tags:
  - "タグ1"
  - "タグ2"
  - "タグ3"
summary: "動画全体の要約を150字程度で簡潔かつ具体的に記述してください。"
---

# {metadata.title}

## 💡 要点 (TL;DR)
- 要点1（本質的・具体的な内容）
- 要点2
- 要点3（3〜5項目）

## 📖 トピック別詳細

### [MM:SS] トピック見出し1
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v={metadata.video_id}&t=開始秒s)

トピックの内容を詳細にまとめます。
- 音声中の該当トピックの開始時間を [MM:SS]（例: [01:23]）として正確に記載してください。
- 該当箇所へのリンクURL末尾の「t=開始秒s」は、該当セクションの開始秒数（例: 01:23 なら t=83s）を正しく計算して記載してください。
- 手順、Tips、重要概念、コマンドや具体例などを明瞭に構造化してください。

### [MM:SS] トピック見出し2
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v={metadata.video_id}&t=開始秒s)

...（動画全体のトピックごとにセクションを分割して作成）

### 指針:
1. 日本語で高品質に出力してください。
2. 音声内の実際の発言に基づき、ハルシネーションを避けてください。
3. 動画全体の主要な展開を漏れなく網羅してください。
"""

        uploaded_file = None
        current_model = self.model_name
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    # 1. Upload audio file if not already uploaded
                    if uploaded_file is None:
                        logger.info(f"Uploading audio file {audio_path.name} to Gemini API (attempt {attempt}/{max_retries})...")
                        uploaded_file = self.client.files.upload(file=str(audio_path))

                        # 2. Wait until file state becomes ACTIVE (Google GenAI processing wait)
                        for _ in range(20):
                            state_str = str(getattr(uploaded_file, "state", "")).upper()
                            if "ACTIVE" in state_str:
                                break
                            if "FAILED" in state_str:
                                raise RuntimeError(f"Geminiサーバー上でのファイル処理に失敗しました (state: {state_str})")
                            time.sleep(1.0)
                            try:
                                uploaded_file = self.client.files.get(name=uploaded_file.name)
                            except Exception as get_err:
                                logger.warning(f"File status poll warning: {get_err}")
                                break

                    # 3. Generate structured markdown
                    response = self.client.models.generate_content(
                        model=current_model,
                        contents=[uploaded_file, audio_prompt],
                        config=types.GenerateContentConfig(
                            temperature=0.2,
                        ),
                    )
                    if not response or not response.text:
                        raise RuntimeError("Gemini APIから空の応答が返されました。")

                    markdown_text = clean_markdown_output(response.text)
                    if not markdown_text.startswith("---"):
                        logger.warning(
                            f"Generated markdown for {metadata.video_id} does not start with YAML frontmatter."
                        )
                    return markdown_text

                except Exception as e:
                    err_str = str(e)

                    # Invalidate file if it became stale or failed state precondition
                    if any(p in err_str.lower() for p in ["failed_precondition", "active state", "not found"]):
                        logger.warning(f"File state invalid on attempt {attempt}: {e}. Discarding to re-upload.")
                        if uploaded_file:
                            try:
                                self.client.files.delete(name=uploaded_file.name)
                            except Exception:
                                pass
                            uploaded_file = None

                    if is_transient_error(e) and attempt < max_retries:
                        wait_sec = initial_backoff * (2 ** (attempt - 1))

                        # If 503 high demand on flash-latest, fallback to flash-lite for next attempt
                        if any(p in err_str.lower() for p in ["503", "unavailable", "high demand"]):
                            if current_model == "gemini-flash-latest":
                                current_model = "gemini-flash-lite-latest"
                                logger.info(
                                    f"Switching audio summarization to fallback model '{current_model}' due to high demand."
                                )

                        logger.warning(
                            f"Transient error on audio {metadata.video_id}: {e}. "
                            f"Retrying with '{current_model}' in {wait_sec}s (attempt {attempt}/{max_retries})..."
                        )
                        if on_retry:
                            try:
                                on_retry(attempt, wait_sec, err_str)
                            except Exception:
                                pass
                        time.sleep(wait_sec)
                        continue
                    raise e

        except Exception as e:
            logger.error(f"Gemini API audio summarization failed for {metadata.video_id}: {e}")
            raise RuntimeError(f"Gemini APIによる音声要約に失敗しました: {e}") from e
        finally:
            if uploaded_file:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                    logger.info(f"Deleted remote Gemini audio file: {uploaded_file.name}")
                except Exception as del_err:
                    logger.warning(f"Failed to delete remote file {uploaded_file.name}: {del_err}")
