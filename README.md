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
| `DEEPGRAM_INTERIM_RESULTS` | Interim出力有無    |              |
| `DEEPGRAM_SMART_FORMAT` | smart_format有無     |              |
| `LLM_PROVIDER`     | `gemini` または `openai`    | ✓            |
| `GOOGLE_API_KEY`   | Google AI APIキー           | Gemini使用時 |
| `OPENAI_API_KEY`   | OpenAI APIキー              | OpenAI使用時 |
| `SOURCE_LANGUAGE`  | 元言語コード (例: `en`)     |              |
| `TARGET_LANGUAGE`  | 翻訳先言語コード (例: `ja`) |              |
| `CONTEXT_WINDOW_SIZE` | 文脈保持の文数           |              |
| `TRANSLATION_QUEUE_SIZE` | 翻訳キューサイズ     |              |
| `DICTIONARY_PATH`  | 用語辞書CSVパス             |              |

## 使い方

```bash
# Zoom RTMS向けCLI
uv run real-time-translation

# Webデモ (Gradio / マイク入力)
uv run real-time-translation-demo
```

WebデモはZoom認証なしで動作します。`DEEPGRAM_API_KEY` と
`LLM_PROVIDER` に応じたAPIキーのみ設定してください。

Gemini利用時はシステムプロンプト/辞書をContext Cachingへ登録するため、
`google-generativeai` がContext Caching対応版であることを前提とします。

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
```
