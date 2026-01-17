# Real-time Translation

Zoomミーティングの音声をリアルタイムに文字起こし・翻訳するシステム

## システム構成

```
Zoom RTMS → AudioCapture → Deepgram WebSocket → LangChain LLM → 翻訳出力
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
| `DEEPGRAM_API_KEY` | Deepgram APIキー            | ✓            |
| `LLM_PROVIDER`     | `gemini` または `openai`    | ✓            |
| `GOOGLE_API_KEY`   | Google AI APIキー           | Gemini使用時 |
| `OPENAI_API_KEY`   | OpenAI APIキー              | OpenAI使用時 |
| `SOURCE_LANGUAGE`  | 元言語コード (例: `en`)     |              |
| `TARGET_LANGUAGE`  | 翻訳先言語コード (例: `ja`) |              |

## 使い方

```bash
# アプリケーションの実行
uv run real-time-translation
```

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
│   └── llm_translator.py   # LLMTranslator (LangChain)
├── __init__.py
├── config.py        # 設定管理
├── main.py          # CLIエントリーポイント
└── pipeline.py      # パイプライン統合
```
