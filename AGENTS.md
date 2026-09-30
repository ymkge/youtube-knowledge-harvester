# YouTube Knowledge Harvester - Agent Guidelines

このファイルは、本リポジトリで作業するAIエージェント（Antigravity, Cursor, Copilot 等）が遵守すべきプロジェクト固有の規約、アーキテクチャ方針、開発ルールを定義したものです。

---

## 1. プロジェクトの基本理念・目的
- **YouTube Knowledge Harvester** は、YouTube動画の字幕とメタデータを取得し、Gemini APIを用いてAIエージェント/RAGが効率的に参照・引用できる**高品質な構造化Markdown（.md）**を一括生成・保存・エクスポートするOSSです。
- **責務の分離（重要）**:
  - 本アプリ内に**ベクトルDB（Chroma, SQLite-vec等）やEmbedding生成処理を組み込まない**でください。
  - 本リポジトリの責務は「高品質・高精度の構造化Markdownを出力すること」に特化し、ベクトル化やインデックス作成は下流のAIエージェント/RAGシステム側に委ねます。

---

## 2. アーキテクチャとディレクトリ構成

```text
.
├── app.py                  # Streamlit Web UIエントリポイント
├── core/
│   ├── __init__.py
│   ├── extractor.py        # yt-dlp / 字幕取得パイプライン
│   ├── summarizer.py       # Gemini API連携・構造化プロンプト管理
│   └── exporter.py         # Markdown保存・ZIPアーカイブ生成
├── tests/                  # ユニットテスト (unittest)
└── output/knowledge/       # デフォルトのMarkdown出力先
```

### 設計原則
- **疎結合設計**: `core/` 配下の各モジュールは Streamlit (`app.py`) に依存せず、独立してCLIや他スクリプトから呼び出し可能であること。
- **データモデル**: 内部のデータ受け渡しには Pydantic モデル（`VideoMetadata`, `SubtitleSnippet`, `VideoTranscriptData`）を使用し、型安全性を確保すること。

---

## 3. RAG向けMarkdownフォーマット要件（厳守）

出力される `.md` ファイルは、以下の仕様を厳格に維持してください。

```markdown
---
title: "動画タイトル"
video_id: "VIDEO_ID"
channel: "チャンネル名"
source_url: "https://www.youtube.com/watch?v=VIDEO_ID"
published_at: "YYYY-MM-DD"
tags:
  - "タグ1"
  - "タグ2"
  - "タグ3"
summary: "動画全体の要約を150字程度で簡潔かつ具体的に記述"
---

# 動画タイトル

## 💡 要点 (TL;DR)
- 要点1
- 要点2
- 要点3（3〜5項目）

## 📖 トピック別詳細

### [MM:SS] トピック見出し
> 🔗 [該当箇所を再生](https://www.youtube.com/watch?v=VIDEO_ID&t=開始秒s)

トピックの内容を詳細にまとめます。
- 手順、Tips、コマンド、重要概念等を明瞭に記述
- URL末尾の「t=開始秒s」はセクション開始秒を正確に計算
```

---

## 4. コーディング・開発ガイドライン

### 言語とスタイル
- **Python**: 3.10以上対応
- **型アノテーション**: `from __future__ import annotations` を利用し、すべての関数・メソッドに適切な型ヒントを付与する。
- **エラーハンドリング**:
  - 字幕取得不可（字幕なし動画）や一時的なAPIエラー時は、**バッチ全体を停止させず、適切にスキップ＆ログ記録**して後続処理を継続すること。
  - エラーログやステータスメッセージはユーザーに分かりやすい表現にする。

### ライブラリ・SDK利用方針
- **Gemini API**: レガシーな `google-generativeai` ではなく、Googleの公式新SDKである **`google-genai`**（`from google import genai`）を使用すること。
- **利用可能モデル**: デフォルトは `gemini-flash-latest`。Streamlit UI上のプルダウンで `gemini-flash-latest` または `gemini-flash-lite-latest` を選択可能とする。
- **動画メタデータ抽出**: `yt-dlp` は `extract_flat=True` を指定し、動画ファイルをダウンロードしないこと。

### セキュリティ・シークレット管理
- **APIキー等のハードコード禁止**: Gemini API Keyやトークンは絶対にコード内に直書きせず、`.env` または環境変数から読み込むこと。
- **Git管理対象外**: `.env`, `output/`, `*.zip`, `.streamlit/secrets.toml` 等は Git コミットに含めないこと。

### Git・GitHub 運用ルール
- **ブランチ運用**: 必ず対応する Issue ごとにブランチを作成して作業すること（命名例: `feature/issue-{番号}-{概要}`, `fix/issue-{番号}-{概要}`）。
- **コミットメッセージ**: 必ず**日本語**で記述すること（例: `feat: エージェント向け設定ファイル群の追加`）。
- **プルリクエスト (PR)**:
  - タイトルおよび Description は必ず**日本語**で記述すること。
  - **Issue の自動クローズ禁止**: PR のマージ時に Issue が自動でクローズされないよう、PR 本文に `Closes #XX`, `Fixes #XX`, `Resolves #XX` などのキーワードを含めないこと（参照する場合は `関連Issue: #XX` と記載する）。

---

## 5. テストと品質検証

機能追加やリファクタリングを行った際は、必ず以下を実行してパスすることを確認してください。

```bash
# 1. ユニットテストの実行
python3 -m unittest discover tests

# 2. 構文チェック
python3 -m py_compile app.py core/*.py
```
