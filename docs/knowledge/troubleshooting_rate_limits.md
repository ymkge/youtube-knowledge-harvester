---
title: "YouTube字幕取得・Gemini APIレート制限のトラブルシューティングと開発ノウハウ"
document_id: "knowledge_rate_limits_and_api_errors"
category: "troubleshooting"
published_at: "2026-09-30"
tags:
  - "YouTube"
  - "youtube-transcript-api"
  - "Gemini API"
  - "Rate Limit"
  - "429 Error"
  - "IpBlocked"
  - "RAG"
  - "Best Practices"
summary: "YouTube動画の字幕抽出とGemini API要約をバッチ実行する際に発生するYouTube側のIPアクセス制限（IpBlocked）およびGemini APIのクォータ制限（429 Too Many Requests）の根本原因、再現メカニズム、および再発防止のためのアーキテクチャ・実装ノウハウをまとめたナレッジ。"
---

# YouTube字幕取得・Gemini APIレート制限のトラブルシューティングと開発ノウハウ

## 💡 要点 (TL;DR)
- **YouTube側のIPブロック (`IpBlocked` / `RequestBlocked`)**: 短時間に連続（例: 0.5秒間隔で数十件）で字幕リクエストを送信すると、GoogleのBot検知フィルターが作動し、`www.youtube.com/api/timedtext` が HTTP 429 / CAPTCHA画面を返して字幕が全件スキップになる。
- **Gemini APIのクォータ超過 (`429 RESOURCE_EXHAUSTED`)**: 長大な字幕テキストを連続送信すると、無料枠（Free Tier: 15 RPM / TPM制限）に即座に達してエラーになる。
- **解決の黄金律**:
  1. **指数バックオフ（Exponential Backoff）**: 429検知時に 10秒 $\rightarrow$ 20秒 $\rightarrow$ 40秒 と待機して自動再試行する。
  2. **適切なリクエストインターバル**: 動画処理間に最低 **2.5〜3.0秒** の待機時間を設ける。
  3. **セッションヘッダー偽装**: `requests.Session` に最新ブラウザの `User-Agent` と `Accept-Language` を設定して `YouTubeTranscriptApi` に渡す。
  4. **差分実行（既存ファイルスキップ）**: 出力先にすでに存在する `.md` をスキップする冪等性を担保し、中断されても未処理分から即座に再開できるようにする。

---

## 📖 発生事象とエラーログ

### 事象
YouTubeチャンネル（約50件の動画）のナレッジ抽出を実行したところ、**初期の2件のみ成功し、残り48件のうち20件が「エラー」、28件が「字幕なしスキップ」**となり、大半の動画が処理されなかった。

```text
走査対象動画: 50
 ├── 生成成功: 2件 （初期の2件のみ通過）
 ├── エラー: 20件 （Gemini API のレートリミット）
 └── 字幕なしスキップ: 28件 （YouTube側によるIP一時制限）
```

### 実際のエラーログ

#### 1. YouTube側のIPブロックログ
```text
Failed to fetch content of selected transcript for {video_id}: 
Could not retrieve a transcript for the video https://www.youtube.com/watch?v={video_id}! 
This is most likely caused by:
YouTube is blocking requests from your IP. This usually is due to:
- You have done too many requests and your IP has been blocked by YouTube
- You are doing requests from an IP belonging to a cloud provider
```
`timedtext` URL を直接叩くと、HTTPステータス `429` と共に `<html><head><title>Sorry...</title>`（GoogleのBot検知・異常トラフィック警告画面）が返されていた。

#### 2. Gemini API側のレート制限ログ
```text
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED: 
Quota exceeded for quota metric 'Generate Content API requests' and limit 'GenerateContent requests per minute' of service 'generativelanguage.googleapis.com'
```

---

## 🔬 原因とメカニズムの深掘り

### 1. なぜ初期の2件だけ成功したのか？
- アプリ起動直後は、YouTube側のIPリクエスト頻度カウンター、およびGemini APIの分間トークン（TPM）・分間リクエスト（RPM）枠が未使用の状態だったため、最初の2件は正常に通過した。

### 2. なぜ3件目以降でGemini APIがエラーになったのか？
- 動画1本の字幕は数千〜2万トークンに達する。
- 待機時間がわずか `0.5秒`（`time.sleep(0.5)`）であったため、1分足らずの間に大量のトークンが送信され、Gemini API Free Tier の **15 RPM（Requests Per Minute）** および **TPM（Tokens Per Minute）** 上限をあっという間に突破した。
- コード内に 429 発生時の待機・リトライロジックが存在しなかったため、即座に例外としてクラッシュ・スキップされた。

### 3. なぜ後半の動画が「字幕なしスキップ」になったのか？
- `youtube-transcript-api` を0.5秒間隔で50回近く高速に叩いた結果、YouTubeのスクレイピング防御機構（レート制限）が発動し、当該IPからの `timedtext` API へのアクセスが一時的にブロックされた。
- ライブラリは `IpBlocked` 例外を投げたが、アプリ側では例外をキャッチして「字幕なし（スキップ）」としてログ出力していたため、実際には字幕が存在する動画であるにもかかわらず全件スキップされる事態となった。

---

## 🛠️ 実装パターンと解決策

### パターン1: Gemini API 指数バックオフ（Retry）の実装
429エラー（`RESOURCE_EXHAUSTED` / `RateLimitExceeded`）を検知した場合、即時終了させずに一時待機してリトライを行う。

```python
# core/summarizer.py
for attempt in range(1, max_retries + 1):
    try:
        response = self.client.models.generate_content(...)
        return clean_markdown_output(response.text)
    except Exception as e:
        err_str = str(e)
        is_rate_limit = any(code in err_str for code in ["429", "RESOURCE_EXHAUSTED", "QuotaExceeded"])
        if is_rate_limit and attempt < max_retries:
            wait_sec = initial_backoff * (2 ** (attempt - 1))  # 10s -> 20s -> 40s
            if on_retry:
                on_retry(attempt, wait_sec, err_str)
            time.sleep(wait_sec)
            continue
        raise e
```

### パターン2: ブラウザセッションヘッダーの注入
デフォルトのPython `requests` User-Agent（例: `python-requests/2.34`）はBot判定されやすいため、最新ブラウザのヘッダーを注入した `Session` を `YouTubeTranscriptApi` に渡す。

```python
# core/extractor.py
import requests
from youtube_transcript_api import YouTubeTranscriptApi

def _get_api_client():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    return YouTubeTranscriptApi(http_client=session)
```

### パターン3: 安全なリクエストインターバルの確保
ループごとのウェイトを 0.5秒 から **3.0秒（推奨: 2.5〜5.0秒）** に拡大。さらに Streamlit UI のサイドバーにスライダー（1.0〜10.0秒）を配置し、APIキーの契約プラン（Free Tier または Pay-as-you-go）に応じて利用者が柔軟に設定できるようにする。

### パターン4: 差分実行（既存ファイルスキップ / 冪等性）
途中でIPブロックやネットワーク断が発生しても、成果物が無駄にならないよう、ローカルに既にファイルが存在する場合は処理をスキップしてメモリにロードする。

```python
# app.py
filename = generate_filename(video, prefix_date=prefix_date_option)
target_file_path = exporter.output_dir / filename

if skip_existing_option and target_file_path.exists():
    existing_content = target_file_path.read_text(encoding="utf-8")
    saved_files[filename] = existing_content
    st.session_state.results.append(...)
    st.session_state.stats["skipped_existing"] += 1
    continue
```

### パターン5: バッチクーリング（定期的なインターバル休憩）
50件や100件などの大量バッチ処理を行う際、各動画間のリクエスト間隔（デフォルト6.0秒）に加えて、**「実アクセスを10件行うごとに45秒〜60秒のクールダウン休憩を自動で挟む」** 仕組みを実装。これにより、ユーザーが手動で分割実行することなく、Google/YouTubeの長期的なレート制限を自動的に回避しながら安全に完走できる。

---

## 📌 今後の開発・運用におけるチェックリスト

1. **バッチ処理時は「0.5秒」のような極端に短い待機時間を避ける**:
   スクレイピングやLLM APIを組み合わせたバッチ処理では、最低でも 2〜3 秒のインターバルを設ける。
2. **例外の分類（原因の可視化）**:
   「字幕が本当に存在しない」のか「IPブロックで取得できなかったのか」をログで明確に区別し、ユーザーが誤認しないようにする。
3. **リトライは指数バックオフで行う**:
   一定間隔（例: 毎回1秒）のリトライは相手サーバーへのDDoS攻撃になり、ブロック期間が延長されるリスクがある。必ずバックオフ係数（2倍ずつ増加）を用いる。
4. **差分処理（キャッシュ機能）を標準装備する**:
   大規模バッチ処理では「再実行可能（冪等性）」であることが最良のUXと堅牢性をもたらす。
