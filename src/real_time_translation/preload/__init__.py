"""Pre-session glossary extraction from presentation materials.

Real simultaneous interpreters ask for slides/abstracts before a talk so
they can pre-load unfamiliar vocabulary. This package is the same idea:
extract candidate terminology from a PDF/PPTX deck (`document_extractor`,
`document_preload`) or straight from video frames when no deck is available
(`video_preload`, added separately), then hand it to `LLMTranslator`/
Deepgram keyterms before the session starts (see `auto_preload`).
"""
