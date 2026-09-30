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
        st.session_state.stats = {
            "success": 0,
            "skipped_existing": 0,
            "no_transcript": 0,
            "error": 0,
            "total": 0,
        }


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

    interval_sec = st.slider(
        "リクエスト間隔 (秒)",
        min_value=1.0,
        max_value=20.0,
        value=6.0,
        step=0.5,
        help="各動画処理ごとの待機時間。YouTubeおよびGemini APIのレート制限（Bot検知や429エラー）を防ぐためデフォルト6.0秒（推奨: 5〜8秒）に設定されています。",
    )

    enable_cooldown = st.checkbox(
        "バッチ休憩（クールダウン）を有効化",
        value=True,
        help="一定件数を処理するごとに安全な待機時間を自動で挟み、大量取得時のBot検知やクォータ超過を防止します。",
    )

    if enable_cooldown:
        col_cd1, col_cd2 = st.columns(2)
        with col_cd1:
            cooldown_every = st.number_input(
                "休憩頻度 (件)",
                min_value=3,
                max_value=30,
                value=10,
                step=1,
                help="何件処理するごとに休憩を挟むかを指定します（デフォルト: 10件）。",
            )
        with col_cd2:
            cooldown_sec = st.number_input(
                "休憩時間 (秒)",
                min_value=10,
                max_value=300,
                value=45,
                step=5,
                help="休憩時の待機秒数を指定します（デフォルト: 45秒）。",
            )
    else:
        cooldown_every = 999999
        cooldown_sec = 0

    prefix_date_option = st.checkbox(
        "ファイル名に投稿日を付加する",
        value=True,
        help="ON: {YYYYMMDD}_{video_id}.md / OFF: {video_id}.md",
    )

    skip_existing_option = st.checkbox(
        "既存ファイルをスキップ (差分実行)",
        value=True,
        help="出力先にすでに存在する動画の再取得・再生成をスキップし、未処理分のみを高速に実行します。",
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
        processed_count = 0  # 実アクセス（字幕取得・API呼び出し）を行った件数カウント

        for idx, video in enumerate(videos, start=1):
            progress_ratio = idx / total_videos
            progress_bar.progress(progress_ratio)

            with status_container.container():
                st.markdown(
                    f"**⏳ [{idx}/{total_videos}] 処理中: [{video.title}]({video.url})**"
                )

            filename = generate_filename(video, prefix_date=prefix_date_option)
            target_file_path = exporter.output_dir / filename

            # 0. 既存ファイルスキップ判定 (差分実行)
            if skip_existing_option and target_file_path.exists():
                try:
                    existing_content = target_file_path.read_text(encoding="utf-8")
                    saved_files[filename] = existing_content
                    st.session_state.results.append(
                        {
                            "title": video.title,
                            "video_id": video.video_id,
                            "url": video.url,
                            "path": str(target_file_path),
                            "filename": filename,
                            "content": existing_content,
                        }
                    )
                    st.session_state.stats["skipped_existing"] += 1
                    append_log(f"⏩ [{idx}/{total_videos}] 既存ファイルを検出したためスキップ: {filename}")
                    continue
                except Exception:
                    pass

            processed_count += 1
            append_log(f"▶ [{idx}/{total_videos}] 字幕を取得中: {video.title} ({video.video_id})")

            # 1. 字幕取得
            transcript_data = fetch_video_transcript(video)
            if not transcript_data:
                append_log(f"⚠️ [{idx}/{total_videos}] 字幕が存在しないか取得できなかったためスキップ: {video.title}")
                st.session_state.stats["no_transcript"] += 1
                time.sleep(interval_sec)
                continue

            append_log(
                f"📝 [{idx}/{total_videos}] 字幕取得成功 (言語: {transcript_data.language}, "
                f"自動生成: {transcript_data.is_generated})。GeminiでMarkdown生成中..."
            )

            # 2. Gemini要約 (リトライ・レート制限対応)
            def on_gemini_retry(attempt: int, wait_sec: float, err: str):
                append_log(
                    f"⏳ [{idx}/{total_videos}] Gemini APIレート制限（429）を検知。"
                    f" {wait_sec:.0f}秒待機して再試行します (試行 {attempt}/3)..."
                )

            try:
                markdown_content = summarizer.summarize(
                    transcript_data,
                    on_retry=on_gemini_retry,
                )
            except Exception as e:
                append_log(f"❌ [{idx}/{total_videos}] Gemini要約失敗 ({video.title}): {e}")
                logger.error(f"Failed to summarize video {video.video_id}: {e}")
                st.session_state.stats["error"] += 1
                time.sleep(interval_sec)
                continue

            # 3. ローカル保存
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

            time.sleep(interval_sec)

            # 4. バッチクールダウン判定 (指定件数ごとの長め休憩)
            if enable_cooldown and processed_count > 0 and (processed_count % cooldown_every == 0) and idx < total_videos:
                append_log(
                    f"☕ [{idx}/{total_videos}件進行中: 実アクセス{processed_count}件完了] "
                    f"YouTube/APIのレート制限・Bot検知を防止するため、{cooldown_sec}秒間のクールダウン待機に入ります..."
                )
                with status_container.container():
                    st.warning(
                        f"☕ レート制限防止のため {cooldown_sec} 秒間クールダウン中... "
                        f"({idx}/{total_videos} 件進行中 / 実アクセス {processed_count} 件完了)"
                    )
                time.sleep(cooldown_sec)

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

    stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns(5)
    stat_col1.metric("走査対象動画", st.session_state.stats["total"])
    stat_col2.metric("新規保存成功", st.session_state.stats["success"])
    stat_col3.metric("既存スキップ", st.session_state.stats.get("skipped_existing", 0))
    stat_col4.metric("字幕なしスキップ", st.session_state.stats["no_transcript"])
    stat_col5.metric("エラー", st.session_state.stats["error"])

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
