"""Translation microservice entrypoint."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from translator_service.llm_translator import LLMTranslator
from translator_service.zoom_caption import ZoomCaptionClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationServiceConfig:
    llm_provider: str
    google_api_key: str | None
    openai_api_key: str | None
    gemini_model: str
    openai_model: str
    source_language: str
    target_language: str
    dictionary_path: Path | None
    ws_publish_url: str
    http_timeout: float
    zoom_caption_url: str | None
    zoom_caption_lang: str | None

    @staticmethod
    def from_env() -> TranslationServiceConfig:
        llm_provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        google_api_key = os.getenv("GOOGLE_API_KEY")
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if llm_provider == "gemini" and not google_api_key:
            raise ValueError("GOOGLE_API_KEY is required when using Gemini")
        if llm_provider == "openai" and not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when using OpenAI")

        dictionary_path = os.getenv("DICTIONARY_PATH")
        return TranslationServiceConfig(
            llm_provider=llm_provider,
            google_api_key=google_api_key,
            openai_api_key=openai_api_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            source_language=os.getenv("SOURCE_LANGUAGE", "en"),
            target_language=os.getenv("TARGET_LANGUAGE", "ja"),
            dictionary_path=Path(dictionary_path) if dictionary_path else None,
            ws_publish_url=os.getenv("WS_PUBLISH_URL", "http://ws:8000/publish"),
            http_timeout=float(os.getenv("HTTP_TIMEOUT", "10")),
            zoom_caption_url=os.getenv("ZOOM_CAPTION_URL"),
            zoom_caption_lang=os.getenv("ZOOM_CAPTION_LANG"),
        )


class TranslateRequest(BaseModel):
    text: str
    context: list[str] = Field(default_factory=list)
    is_final: bool = True
    ts: float | None = None
    session_id: str | None = None


class TranslateResponse(BaseModel):
    translated: str
    kept_terms: list[str] = Field(default_factory=list)
    is_final: bool
    ts: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    config = TranslationServiceConfig.from_env()
    api_key = (
        config.google_api_key
        if config.llm_provider == "gemini"
        else config.openai_api_key
    )
    model = (
        config.gemini_model if config.llm_provider == "gemini" else config.openai_model
    )

    translator = LLMTranslator(
        provider=config.llm_provider,  # type: ignore[arg-type]
        api_key=api_key or "",
        model=model,
        source_language=config.source_language,
        target_language=config.target_language,
        dictionary_path=config.dictionary_path,
    )
    await translator.prepare()

    http_client = httpx.AsyncClient(timeout=config.http_timeout)
    
    # Initialize Zoom caption client if URL is configured
    zoom_caption: ZoomCaptionClient | None = None
    if config.zoom_caption_url:
        zoom_caption = ZoomCaptionClient(
            caption_url=config.zoom_caption_url,
            http_client=http_client,
            lang=config.zoom_caption_lang,
        )
        await zoom_caption.sync_seq()
        logger.info("Zoom caption client initialized")
    
    app.state.config = config
    app.state.translator = translator
    app.state.http_client = http_client
    app.state.zoom_caption = zoom_caption
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _publish_translation(
    http_client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
) -> None:
    try:
        await http_client.post(url, json=payload)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to publish translation update")


@app.post("/translate", response_model=TranslateResponse)
async def translate(request: TranslateRequest) -> TranslateResponse:
    translator: LLMTranslator = app.state.translator
    config: TranslationServiceConfig = app.state.config
    http_client: httpx.AsyncClient = app.state.http_client
    zoom_caption: ZoomCaptionClient | None = app.state.zoom_caption

    output = await translator.translate(
        request.text,
        context_lines=request.context,
        update_context=False,
    )

    ts = request.ts or time.time()
    payload = {
        "type": "translation",
        "src": request.text,
        "translated": output.latest_slide,
        "kept_terms": output.kept_terms,
        "is_final": request.is_final,
        "ts": ts,
        "session_id": request.session_id,
    }
    await _publish_translation(http_client, config.ws_publish_url, payload)
    
    # Send caption to Zoom if configured and this is a final result
    if zoom_caption and request.is_final:
        await zoom_caption.send_caption(output.latest_slide)

    return TranslateResponse(
        translated=output.latest_slide,
        kept_terms=output.kept_terms,
        is_final=request.is_final,
        ts=ts,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
