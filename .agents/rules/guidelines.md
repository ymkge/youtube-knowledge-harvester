# YouTube Knowledge Harvester Rules

## プロジェクト原則
- **アプリ内ベクトルDB禁止**: 本リポジトリ内にベクトルストア（Chroma, FAISS, SQLite-vec 等）やEmbedding生成処理を追加しないでください。Markdownファイルの生成・保存に特化します。
- **google-genai SDK準拠**: Gemini APIの呼び出しには `google-genai` SDK（`from google import genai`）を使用してください（`google-generativeai` は非推奨）。
- **非破壊的エラーハンドリング**: 字幕なし動画やAPIエラーが発生しても、バッチ全体をクラッシュさせずにスキップしてログ出力を行ってください。
- **テストの実行**: コード変更後は必ず `python3 -m unittest discover tests` を実行して検証してください。

## 開発・プルリクエスト運用ワークフロー（厳守）
1. **Issue発行 & 実装計画書の作成**:
   - Issueごとにブランチ（`feature/issue-{番号}-{概要}`, `fix/issue-{番号}-{概要}`）を作成。
   - すぐに実装せず、まず**実装計画書（Implementation Plan）**を作成して提示する。
   - ユーザーからの **「OK / NG」の連絡を待ち、OK受領まで実装を開始しない** こと。
2. **実装 & ウォークスルーの作成**:
   - 計画書OK受領後、実装とテストを実施。
   - 実装終了時点で**ウォークスルー（Walkthrough）**を作成して提示する。
   - ユーザーからの **「確認・OK」の連絡を待ち、OK受領までPR作成に進まない** こと。
3. **プルリクエスト（PR）の作成**:
   - ウォークスルーOK受領後、PRを作成。
   - タイトルおよび **Description（概要・変更点・検証内容・関連Issue）を同時に日本語で作成** して提示する。
   - コミットメッセージは必ず日本語。
   - **Issueの自動クローズ禁止**: PR本文に `Closes #XX`, `Fixes #XX` 等を含めない（`関連Issue: #XX` と記載）。
4. **マージ後のブランチ整理**:
   - ユーザーがレビューを行い `main` にマージした後、マージ済みの作業ブランチを綺麗に削除・整理する。
