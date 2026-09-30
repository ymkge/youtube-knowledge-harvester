# YouTube Knowledge Harvester Rules

## プロジェクト原則
- **アプリ内ベクトルDB禁止**: 本リポジトリ内にベクトルストア（Chroma, FAISS, SQLite-vec 等）やEmbedding生成処理を追加しないでください。Markdownファイルの生成・保存に特化します。
- **google-genai SDK準拠**: Gemini APIの呼び出しには `google-genai` SDK（`from google import genai`）を使用してください（`google-generativeai` は非推奨）。
- **非破壊的エラーハンドリング**: 字幕なし動画やAPIエラーが発生しても、バッチ全体をクラッシュさせずにスキップしてログ出力を行ってください。
- **テストの実行**: コード変更後は必ず `python3 -m unittest discover tests` を実行して検証してください。

## Git・GitHub 運用ルール
- **ブランチ運用**: 必ず対応する Issue ごとにブランチを作成して作業すること（命名例: `feature/issue-{番号}-{概要}`）。
- **コミットメッセージ**: 必ず**日本語**で記述すること（例: `feat: エージェント向け設定ファイル群の追加`）。
- **プルリクエスト (PR)**:
  - タイトル・Description は必ず**日本語**で記述すること。
  - **Issue の自動クローズ禁止**: PR 本文に `Closes #XX`, `Fixes #XX`, `Resolves #XX` などのキーワードを含めないこと（参照表記は `関連Issue: #XX` とする）。
