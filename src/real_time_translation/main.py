"""Main entry point for real-time translation."""

import asyncio
import signal

from real_time_translation.audio.capture import ZoomRTMSCapture, ZoomRTMSConfig
from real_time_translation.config import Config
from real_time_translation.pipeline import TranslationPipeline, TranslationResult


def print_result(result: TranslationResult) -> None:
    """Print translation result to console.

    Args:
        result: Translation result to print
    """
    status = "✓" if result.is_final else "..."
    confidence = f"({result.confidence:.0%})" if result.confidence < 0.9 else ""

    print(f"\n{status} Original: {result.original_text}")
    print(f"  Translated: {result.translated_text} {confidence}")


async def run_pipeline() -> None:
    """Run the translation pipeline."""
    # Load configuration
    config = Config.from_env()

    # Create audio capture with Zoom RTMS
    rtms_config = ZoomRTMSConfig(
        client_id=config.zoom_client_id,
        client_secret=config.zoom_client_secret,
        webhook_port=config.zoom_webhook_port,
        webhook_path=config.zoom_webhook_path,
    )
    audio_capture = ZoomRTMSCapture(rtms_config)

    # Create pipeline
    pipeline = TranslationPipeline(
        config=config,
        audio_capture=audio_capture,
    )

    # Set result callback
    pipeline.set_callback(print_result)

    # Handle shutdown
    loop = asyncio.get_running_loop()

    def shutdown() -> None:
        asyncio.create_task(pipeline.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    print("Starting real-time translation...")
    print(
        f"Webhook server: http://localhost:{config.zoom_webhook_port}{config.zoom_webhook_path}"
    )
    print("Press Ctrl+C to stop")
    print("-" * 50)

    await pipeline.run()


def main() -> None:
    """Entry point for the application."""
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
