## システム要件定義

### 1. システム概要

本システムは、Zoomの音声をリアルタイムに文字起こしし、翻訳して表示するシステムである。

### 2. 機能要件

- Zoomからの音声データをリアルタイムに取得する
- 取得した音声データを文字起こしする
- 文字起こしされたテキストを翻訳する
- 翻訳結果をリアルタイムに表示する

### 3. 非機能要件

- リアルタイム性：音声データ取得から翻訳結果表示までの遅延は最小限に抑える
  - 目標としては1秒以下、できれば0.5秒以内
- 精度：文字起こし、翻訳の精度は十分に高いこと
- 安定性：システムは安定して動作し、エラーが少ないこと
- 拡張性：将来的な機能追加や性能向上に対応できる設計であること

### 4. システム構成

- 音声認識：Deepgram or Aqua Voice or assemblyAI
  - Deepgram: https://deepgram.com/
    - 200$ free usage 有り
    - リアルタイム処理：
      - https://deepgram.com/learn/streaming-speech-recognition-api
      - https://developers.deepgram.com/docs/flux/quickstart
      - WebSocketを利用して通信をしている
      - confidencialの取得が可能なので低い場合は[MASK]のようにしてLLMに行間を読ませる？
  - Aqua Voice
    - https://aquavoice.com/avalon-api
    - リアルタイムの記述なし
  - assemblyAI
    - https://www.assemblyai.com/docs/api-reference/overview
    - REST APIを利用
    - リアルタイム処理の実装：
      - https://www.assemblyai.com/docs/guides/transcribe_system_audio
      - https://www.assemblyai.com/docs/universal-streaming
- 翻訳：Gemini 3.0 Flash or ChatGPT-5 mini/nano
  - Prompt Caching / Context Caching: 辞書入力のキャッシング
    - OpenAI: https://platform.openai.com/docs/guides/prompt-caching + Streaming
      API
    - Gemini: https://ai.google.dev/gemini-api/docs/caching?lang=python
  - Open AI Translation: https://chatgpt.com/translate
- ワークフロー制御：LangChain

### 5. インターフェース

- YouTube API：ライブストリームの音声データ取得
- Deepgram API：音声データの文字起こし
- Gemini API：テキストの翻訳
- LangChain：各APIの連携、ワークフロー制御

### 6. その他

- 辞書：特定の分野の専門用語を登録し、翻訳精度向上に利用する
