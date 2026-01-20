# Real-time Translation

Zoomミーティングの音声をリアルタイムに文字起こし・翻訳するシステム

## システム構成

```
Zoom RTMS → AudioCapture → Deepgram WebSocket → LLM (Gemini/OpenAI) → 翻訳出力
```

## セットアップ

```bash
# 依存関係のインストール
uv sync --extra dev

# 環境変数の設定
cp .env.example .env
# .envファイルを編集してAPIキーを設定
```

## 環境変数

| 変数名             | 説明                        | 必須         |
| ------------------ | --------------------------- | ------------ |
| `ZOOM_CLIENT_ID`   | Zoom RTMS Client ID         | Zoom使用時   |
| `ZOOM_CLIENT_SECRET` | Zoom RTMS Client Secret   | Zoom使用時   |
| `DEEPGRAM_API_KEY` | Deepgram APIキー            | ✓            |
| `DEEPGRAM_MODEL`   | Deepgramモデル名            |              |
| `DEEPGRAM_ENDPOINTING` | 無音検知の確定(ms)      |              |
| `DEEPGRAM_UTTERANCE_END_MS` | 発話終了検知(ms) |              |
| `DEEPGRAM_INTERIM_RESULTS` | Interim出力有無    |              |
| `DEEPGRAM_SMART_FORMAT` | smart_format有無     |              |
| `DEEPGRAM_VAD_EVENTS` | VADイベント有無        |              |
| `LLM_PROVIDER`     | `gemini` または `openai`    | ✓            |
| `GOOGLE_API_KEY`   | Google AI APIキー           | Gemini使用時 |
| `OPENAI_API_KEY`   | OpenAI APIキー              | OpenAI使用時 |
| `SOURCE_LANGUAGE`  | 元言語コード (例: `en`)     |              |
| `TARGET_LANGUAGE`  | 翻訳先言語コード (例: `ja`) |              |
| `CONTEXT_WINDOW_SIZE` | 文脈保持の文数           |              |
| `TRANSLATION_QUEUE_SIZE` | 翻訳キューサイズ     |              |
| `DICTIONARY_PATH`  | 用語辞書CSVパス             |              |

`DEEPGRAM_UTTERANCE_END_MS` を設定すると、UtteranceEndイベントで
直近のinterim結果を確定として扱い、文脈のまとまりを優先できます。

### マイクロサービス用追加環境変数

| 変数名 | 説明 | 必須 |
| --- | --- | --- |
| `RTMP_URL` | NMSのRTMP入力URL | ✓ |
| `WS_PUBLISH_URL` | WSサービスへのPublish URL | ✓ |
| `TRANSLATION_API_URL` | 翻訳API URL | ✓ |
| `ASR_SEND_INTERIM` | ASRのinterimをWSへ送信 | |
| `TRANSLATE_INTERIM` | interimを翻訳へ送信 | |
| `ASR_PARTIAL_MIN_INTERVAL_MS` | interim送信間隔(ms) | |
| `TRANSLATION_CONCURRENCY` | 翻訳同時実行数 | |
| `HTTP_TIMEOUT` | HTTPタイムアウト(秒) | |

## 使い方

```bash
# Zoom RTMS向けCLI
uv run real-time-translation

# Webデモ (Gradio / マイク入力)
uv run real-time-translation-demo

# マイクロサービス単体起動
uv run real-time-translation-ws
uv run real-time-translation-translate
uv run real-time-translation-asr
```

WebデモはZoom認証なしで動作します。`DEEPGRAM_API_KEY` と
`LLM_PROVIDER` に応じたAPIキーのみ設定してください。

## Docker マイクロサービス構成

```bash
# Docker Composeで起動
docker compose up --build
```

- RTMP 取り込み: `rtmp://localhost:1935/live/zoom`
- 字幕 WebSocket: `ws://localhost:8000/ws/caption`
- Node-Media-Server HTTP: `http://localhost:8001`

主なサービス:
- `deepgram`: RTMP → Deepgram ASR、ASR結果をWS/翻訳へ中継
- `gemini`: 翻訳API (FastAPI)、翻訳結果をWSへ配信
- `ws`: 字幕配信用WebSocket (FastAPI)

マイクロサービス用の環境変数例は `.env.example` に追加済みです。

Gemini利用時は `google.genai` (google-genai) のContext Cachingで
システムプロンプト/辞書をキャッシュし、LangChainの
`ChatGoogleGenerativeAI(cached_content=...)` 経由で参照します。
Context Cacheは最小トークン数の制約があるため、プロンプトが小さい場合は
自動的に `<cache_padding>` を付与してキャッシュを作成します。

翻訳はStructured Outputで `latest_slide`（最新の翻訳）と `kept_terms`
（固有名詞/曖昧語として保持した語）を返し、Webデモでは直近
`CONTEXT_WINDOW_SIZE` 文のスライドウィンド表示を行います。

## 開発

```bash
# テストの実行
uv run pytest

# コードフォーマット
uv run ruff format .

# リント
uv run ruff check .
```

## プロジェクト構造

```
src/real_time_translation/
├── audio/           # 音声取得モジュール
│   ├── __init__.py
│   └── capture.py   # AudioCapture, ZoomRTMSCapture
├── transcription/   # 文字起こしモジュール
│   ├── __init__.py
│   └── deepgram_client.py  # DeepgramTranscriber
├── translation/     # 翻訳モジュール
│   ├── __init__.py
│   └── llm_translator.py   # LLMTranslator (Gemini/OpenAI)
├── __init__.py
├── config.py        # 設定管理
├── gradio_demo.py   # Gradioデモ
├── main.py          # CLIエントリーポイント
└── pipeline.py      # パイプライン統合
services/
├── asr/             # ASRサービス用Dockerfile
├── translator/      # 翻訳サービス用Dockerfile
└── ws/              # WebSocket配信サービス用Dockerfile
```
