"""Streamlit Web UI for YouTube Knowledge Harvester."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, List

import streamlit as st
from dotenv import load_dotenv

from core.exporter import MarkdownExporter, generate_filename
from core.extractor import (
    VideoMetadata,
    VideoTranscriptData,
    fetch_channel_videos,
    fetch_video_transcript,
)
from core.summarizer import AVAILABLE_MODELS, DEFAULT_MODEL, GeminiSummarizer

# Load .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="YouTube Knowledge Harvester",
    page_icon="🎬",
    layout="wide",
)


def init_session_state():
    """Initialize Streamlit session state variables."""
    if "is_processing" not in st.session_state:
        st.session_state.is_processing = False
    if "results" not in st.session_state:
        st.session_state.results = []
    if "logs" not in st.session_state:
        st.session_state.logs = []
    if "zip_data" not in st.session_state:
        st.session_state.zip_data = None
    if "stats" not in st.session_state:
        st.session_state.stats = {"success": 0, "no_transcript": 0, "error": 0, "total": 0}


init_session_state()

# ----------------- Sidebar Configuration -----------------
with st.sidebar:
    st.header("⚙️ 設定 (Settings)")

    env_api_key = os.environ.get("GEMINI_API_KEY", "")
    api_key_input = st.text_input(
        "Gemini API Key",
        value=env_api_key,
        type="password",
        help="Gemini APIを利用するためのキー。.env に GEMINI_API_KEY を設定している場合は自動入力されます。",
    )

    model_input = st.selectbox(
        "Gemini モデル",
        options=AVAILABLE_MODELS,
        index=0,
        help="利用するGeminiモデルを選択してください（デフォルト: gemini-flash-latest）。",
    )

    prefix_date_option = st.checkbox(
        "ファイル名に投稿日を付加する",
        value=True,
        help="ON: {YYYYMMDD}_{video_id}.md / OFF: {video_id}.md",
    )

    st.markdown("---")
    st.markdown("### 💡 について")
    st.caption(
        "YouTube Knowledge Harvester は、チャンネルの直近動画から字幕を取得し、"
        "AIエージェント（RAG）が参照しやすい構造化Markdownファイルを一括生成・保存します。"
    )

# ----------------- Main UI -----------------
st.title("🎬 YouTube Knowledge Harvester")
st.markdown(
    "YouTubeチャンネルから字幕付き動画を走査し、Gemini APIで高品質な **RAG用構造化Markdown** を自動生成します。"
)

with st.form("harvester_form"):
    channel_url = st.text_input(
        "YouTubeチャンネルURL *",
        placeholder="https://www.youtube.com/@channel_name または https://www.youtube.com/channel/UC...",
        help="抽出対象のYouTubeチャンネルURLを入力してください。",
    )

    col1, col2 = st.columns(2)
    with col1:
        max_videos = st.number_input(
            "取得動画件数 (直近 n 件)",
            min_value=1,
            max_value=200,
            value=50,
            step=5,
            help="取得する最新動画の件数を指定します（1〜200）。",
        )
    with col2:
        output_dir = st.text_input(
            "ローカル出力先ディレクトリ",
            value="./output/knowledge/",
            help="生成されたMarkdownファイルの保存先パス。",
        )

    submit_button = st.form_submit_button(
        "🚀 ナレッジ抽出を開始",
        use_container_width=True,
        type="primary",
        disabled=st.session_state.is_processing,
    )

# ----------------- Processing Logic -----------------
if submit_button:
    if not channel_url.strip():
        st.error("YouTubeチャンネルURLを入力してください。")
    elif not api_key_input.strip():
        st.error("Gemini API Key を入力するか、.env ファイルに GEMINI_API_KEY を設定してください。")
    else:
        st.session_state.is_processing = True
        st.session_state.results = []
        st.session_state.logs = []
        st.session_state.zip_data = None
        st.session_state.stats = {"success": 0, "no_transcript": 0, "error": 0, "total": 0}

        try:
            summarizer = GeminiSummarizer(api_key=api_key_input.strip(), model=model_input.strip())
            exporter = MarkdownExporter(output_dir=output_dir.strip())
        except Exception as e:
            st.error(f"初期化エラー: {e}")
            st.session_state.is_processing = False
            st.stop()

        status_container = st.empty()
        progress_bar = st.progress(0)
        log_expander = st.expander("📝 リアルタイム実行ログ", expanded=True)
        log_placeholder = log_expander.empty()

        def append_log(message: str):
            st.session_state.logs.append(message)
            log_placeholder.markdown("\n".join(st.session_state.logs[-20:]))

        with status_container.container():
            st.info("📡 チャンネル動画一覧を取得中...")

        try:
            videos: List[VideoMetadata] = fetch_channel_videos(
                channel_url=channel_url.strip(),
                max_results=int(max_videos),
            )
        except Exception as e:
            st.error(f"チャンネル走査中にエラーが発生しました: {e}")
            st.session_state.is_processing = False
            st.stop()

        if not videos:
            st.warning("動画が見つかりませんでした。URLを確認してください。")
            st.session_state.is_processing = False
            st.stop()

        total_videos = len(videos)
        st.session_state.stats["total"] = total_videos
        append_log(f"✅ 合計 {total_videos} 件の動画メタデータを検出しました。順次字幕取得・要約を開始します。")

        saved_files: Dict[str, str] = {}

        for idx, video in enumerate(videos, start=1):
            progress_ratio = idx / total_videos
            progress_bar.progress(progress_ratio)

            with status_container.container():
                st.markdown(
                    f"**⏳ [{idx}/{total_videos}] 処理中: [{video.title}]({video.url})**"
                )

            append_log(f"▶ [{idx}/{total_videos}] 字幕を取得中: {video.title} ({video.video_id})")

            # 1. 字幕取得
            transcript_data = fetch_video_transcript(video)
            if not transcript_data:
                append_log(f"⚠️ [{idx}/{total_videos}] 字幕が存在しないか取得できなかったためスキップ: {video.title}")
                st.session_state.stats["no_transcript"] += 1
                continue

            append_log(
                f"📝 [{idx}/{total_videos}] 字幕取得成功 (言語: {transcript_data.language}, "
                f"自動生成: {transcript_data.is_generated})。GeminiでMarkdown生成中..."
            )

            # 2. Gemini要約
            try:
                markdown_content = summarizer.summarize(transcript_data)
            except Exception as e:
                append_log(f"❌ [{idx}/{total_videos}] Gemini要約失敗 ({video.title}): {e}")
                logger.error(f"Failed to summarize video {video.video_id}: {e}")
                st.session_state.stats["error"] += 1
                continue

            # 3. ローカル保存
            filename = generate_filename(video, prefix_date=prefix_date_option)
            try:
                saved_path = exporter.save_markdown(filename, markdown_content)
                saved_files[filename] = markdown_content
                st.session_state.results.append(
                    {
                        "title": video.title,
                        "video_id": video.video_id,
                        "url": video.url,
                        "path": str(saved_path),
                        "filename": filename,
                        "content": markdown_content,
                    }
                )
                st.session_state.stats["success"] += 1
                append_log(f"✨ [{idx}/{total_videos}] 保存完了: {filename}")
            except Exception as e:
                append_log(f"❌ [{idx}/{total_videos}] 保存失敗 ({filename}): {e}")
                st.session_state.stats["error"] += 1

            time.sleep(0.5)  # Rate limiting buffer

        # ZIPアーカイブ作成
        if saved_files:
            st.session_state.zip_data = MarkdownExporter.create_zip_archive(saved_files)

        progress_bar.progress(1.0)
        status_container.success(f"🎉 処理が完了しました！（全 {total_videos} 件中 {len(saved_files)} 件保存）")
        st.session_state.is_processing = False

# ----------------- Results & Download Section -----------------
if st.session_state.results:
    st.markdown("---")
    st.subheader("📊 処理結果サマリー")

    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    stat_col1.metric("走査対象動画", st.session_state.stats["total"])
    stat_col2.metric("生成成功", st.session_state.stats["success"])
    stat_col3.metric("字幕なしスキップ", st.session_state.stats["no_transcript"])
    stat_col4.metric("エラー", st.session_state.stats["error"])

    # Download Button
    if st.session_state.zip_data:
        st.download_button(
            label="📦 生成された全MarkdownファイルをZIPでダウンロード",
            data=st.session_state.zip_data,
            file_name="youtube_knowledge_base.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )

    st.markdown("### 📄 生成されたナレッジプレビュー")
    for item in st.session_state.results:
        with st.expander(f"📑 {item['filename']} — {item['title']}"):
            st.caption(f"保存先パス: `{item['path']}` | [元動画を開く]({item['url']})")
            st.markdown(item["content"])
