# YouTube Knowledge Harvester 🎬📚

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Gemini API](https://img.shields.io/badge/Powered%20by-Gemini%202.5%20Flash-4E75F6.svg)](https://ai.google.dev/)

YouTubeチャンネルの直近動画から字幕・メタデータを取得し、Gemini APIを用いてAIエージェント（RAG: Retrieval-Augmented Generation）が参照しやすい**構造化Markdown（.md）ファイル**を一括生成・保存・エクスポートするオープンソースのローカルWebアプリケーションです。

---

## 🌟 特徴

- ⚡ **高速メタデータ抽出**: `yt-dlp` のメタデータ走査 (`extract_flat=True`) により、動画をダウンロードすることなく直近指定件数（1〜200件）の動画情報を瞬時に取得。
- 🎙️ **多言語フォールバック字幕取得**: `youtube-transcript-api` を利用し、日本語手動字幕 $\rightarrow$ 日本語自動生成字幕 $\rightarrow$ 英語字幕 $\rightarrow$ その他字幕 の順でスマートに取得。字幕が存在しない動画は自動スキップしバッチ処理を継続。
- 🤖 **Gemini 2.5 Flash による高品質要約**: タイムスタンプ付き字幕を構造化し、TL;DR、トピック別詳細、該当再生秒数リンク付きのMarkdownを出力。
- 📂 **RAG最適化フォーマット**:
  - YAML Frontmatter にメタデータ（タイトル、動画ID、チャンネル名、URL、投稿日、タグ、150字サマリー）を完全保持。
  - セクション見出しに開始タイムスタンプと動画のダイレクト再生URL（`t=開始秒s`）を付与。
- 💾 **即時ローカル保存 & 一括ZIPダウンロード**: 指定フォルダへのダイレクト保存に加え、Web UI上からワンクリックで全ファイルをZIPダウンロード可能。
- 🧩 **クリーンアーキテクチャ**: アプリ内に独自のベクトルDBを持たず、純粋なMarkdownファイル群を出力するため、Antigravity CLI、Cursor、Claude、ChatGPT等の各種AIエージェントや既存RAGパイプラインにそのまま組み込めます。

---

## 📋 ディレクトリ構成

```text
.
├── .env.example            # 環境変数設定テンプレート
├── .gitignore
├── README.md               # ドキュメント（本ファイル）
├── requirements.txt        # 依存ライブラリ一覧
├── app.py                  # Streamlit Web UIエントリポイント
├── core/
│   ├── __init__.py
│   ├── extractor.py        # yt-dlp / 字幕取得パイプライン
│   ├── summarizer.py       # Gemini API連携・構造化プロンプト管理
│   └── exporter.py         # Markdown保存・ZIPアーカイブ生成
└── output/
    └── knowledge/          # デフォルトのMarkdown出力先
```

---

## 🚀 クイックスタート

### 1. リポジトリのクローン & 移動

```bash
git clone https://github.com/your-username/youtube-knowledge-harvester.git
cd youtube-knowledge-harvester
```

### 2. Python仮想環境の準備と依存パッケージのインストール

Python 3.10以上を推奨します。

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、Gemini APIキーを設定します。

```bash
cp .env.example .env
```

`.env` を編集:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```
> [!TIP]
> Gemini API Keyは [Google AI Studio](https://aistudio.google.com/) から無料で即座に取得できます。Web UI上のサイドバーから直接入力・上書きすることも可能です。

### 4. Web UIの起動

```bash
streamlit run app.py
```

ブラウザで `http://localhost:8501` が自動的に開きます。

---

## 🖥️ 使い方

1. **YouTubeチャンネルURL**: 対象チャンネルのURLを入力（例: `https://www.youtube.com/@channel_name`）
2. **取得動画件数**: 直近何件の動画を取得するか指定（デフォルト: 50件、最大: 200件）
3. **ローカル出力先ディレクトリ**: Markdownファイルの保存先（デフォルト: `./output/knowledge/`）
4. **「ナレッジ抽出を開始」をクリック**:
   - リアルタイムに進捗バーとログが更新されます。
   - 字幕のない動画はスキップされ、全体の処理は中断されません。
5. **完了後**:
   - ローカルフォルダへ `{YYYYMMDD}_{video_id}.md` 形式で直接保存されます。
   - 「生成された全MarkdownファイルをZIPでダウンロード」ボタンから一括ダウンロードも可能です。

---

## 📄 生成されるMarkdownの仕様 (RAG最適化)

生成される各ファイルは、LLMエージェントがメタデータ検索および本文参照を行いやすいように設計されています。

```markdown
---
title: "動画タイトル"
video_id: "dQw4w9WgXcQ"
channel: "チャンネル名"
source_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
published_at: "2024-01-15"
tags:
  - "AI"
  - "Python"
  - "RAG"
summary: "本動画では、最新のAIエージェントアーキテクチャとRAGパイプラインの構築手法について解説しています。"
---

# 動画タイトル

## 💡 要点 (TL;DR)
- 要点1
- 要点2
- 要点3

## 📖 トピック別詳細

### [00:45] はじめに：AIエージェントの概要
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=45s)

概要と背景の説明...

### [03:20] 実践チュートリアルと環境構築
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=200s)

具体的なコマンドや手順、注意事項...
```

---

## 🤖 AIエージェント（Antigravity CLI / Cursor 等）での活用法

出力された Markdown ファイル群は、ベクトル検索やエージェントのコンテキストとしてそのまま活用できます。

### 1. Antigravity CLI や Claude Code 等のコーディングエージェント
プロジェクト直下に `output/knowledge/` を置いたままエージェントを実行すると、エージェントはFrontmatterや見出しを自然にgrep/参照し、最新のナレッジやチュートリアルを参照したコーディングを行えます。

### 2. Cursor / VS Code (RAG & Codebase Indexing)
Cursorの「Docs」やコードベースインデックス対象に `output/knowledge/` を指定することで、動画内の解説やTipsをチャット内で参照できます。

### 3. LangChain / LlamaIndex
マークダウンローダー（`UnstructuredMarkdownLoader` や `DirectoryLoader`）を用いてインジェストし、Frontmatterをチャンクのメタデータとして保持したベクトルストアを簡単に構築できます。

---

## 🛠️ トラブルシューティング

- **「チャンネル情報の取得に失敗しました」と表示される場合:**
  - YouTubeチャンネルのURL形式を確認してください（例: `https://www.youtube.com/@GoogleCloudTech`）。
  - インターネット接続を確認してください。
- **「字幕が存在しないか取得できなかったためスキップ」が連続する場合:**
  - そのチャンネルの動画で字幕（手動または自動生成）が有効化されているか確認してください。音楽動画や字幕のないショート動画はスキップ対象となります。
- **Gemini APIのエラー (429 Too Many Requests 等):**
  - 無料枠のクォータ上限に達した可能性があります。リクエスト間隔をあけるか、有料プラン（従量課金）のキーをご利用ください。

---

## 📜 ライセンス

本プロジェクトは [MIT License](LICENSE) の下で公開されています。
