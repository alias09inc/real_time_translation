"""Configuration management for real-time translation."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration."""

    # Deepgram
    deepgram_api_key: str

    # LLM Provider (gemini or openai)
    llm_provider: str

    # Zoom RTMS
    zoom_client_id: str
    zoom_client_secret: str

    # Deepgram options
    deepgram_model: str = "nova-2-general"
    deepgram_interim_results: bool = True
    deepgram_smart_format: bool = True
    deepgram_endpointing: int = 500
    zoom_webhook_port: int = 8080
    zoom_webhook_path: str = "/webhook"

    # Gemini
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Translation settings
    source_language: str = "en"
    target_language: str = "ja"
    context_window_size: int = 3
    translation_queue_size: int = 10

    # Dictionary
    dictionary_path: Path | None = None

    @classmethod
    def from_env(
        cls, env_file: Path | None = None, *, require_zoom: bool = True
    ) -> "Config":
        """Load configuration from environment variables.

        Args:
            env_file: Optional path to .env file
            require_zoom: Whether Zoom RTMS credentials are required

        Returns:
            Config instance
        """
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        deepgram_api_key = os.getenv("DEEPGRAM_API_KEY", "")
        if not deepgram_api_key:
            raise ValueError("DEEPGRAM_API_KEY is required")

        def _get_bool_env(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        # Zoom RTMS credentials
        zoom_client_id = os.getenv("ZOOM_CLIENT_ID", "")
        zoom_client_secret = os.getenv("ZOOM_CLIENT_SECRET", "")
        if require_zoom and (not zoom_client_id or not zoom_client_secret):
            raise ValueError("ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET are required")

        llm_provider = os.getenv("LLM_PROVIDER", "gemini").lower()

        google_api_key = os.getenv("GOOGLE_API_KEY")
        openai_api_key = os.getenv("OPENAI_API_KEY")

        if llm_provider == "gemini" and not google_api_key:
            raise ValueError("GOOGLE_API_KEY is required when using Gemini")
        if llm_provider == "openai" and not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when using OpenAI")

        # Dictionary path
        dictionary_path_str = os.getenv("DICTIONARY_PATH")
        dictionary_path = Path(dictionary_path_str) if dictionary_path_str else None

        return cls(
            deepgram_api_key=deepgram_api_key,
            deepgram_model=os.getenv("DEEPGRAM_MODEL", "nova-2-general"),
            deepgram_interim_results=_get_bool_env("DEEPGRAM_INTERIM_RESULTS", True),
            deepgram_smart_format=_get_bool_env("DEEPGRAM_SMART_FORMAT", True),
            deepgram_endpointing=int(os.getenv("DEEPGRAM_ENDPOINTING", "500")),
            llm_provider=llm_provider,
            zoom_client_id=zoom_client_id,
            zoom_client_secret=zoom_client_secret,
            zoom_webhook_port=int(os.getenv("ZOOM_WEBHOOK_PORT", "8080")),
            zoom_webhook_path=os.getenv("ZOOM_WEBHOOK_PATH", "/webhook"),
            google_api_key=google_api_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            openai_api_key=openai_api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            source_language=os.getenv("SOURCE_LANGUAGE", "en"),
            target_language=os.getenv("TARGET_LANGUAGE", "ja"),
            context_window_size=int(os.getenv("CONTEXT_WINDOW_SIZE", "3")),
            translation_queue_size=int(os.getenv("TRANSLATION_QUEUE_SIZE", "10")),
            dictionary_path=dictionary_path,
        )
