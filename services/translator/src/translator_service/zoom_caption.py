"""Zoom closed caption HTTP client."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)


class ZoomCaptionClient:
    """Client for sending captions to Zoom via HTTP POST.
    
    Reference: https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060372
    """

    def __init__(
        self,
        caption_url: str,
        http_client: httpx.AsyncClient,
        lang: str | None = None,
    ) -> None:
        """Initialize the Zoom caption client.
        
        Args:
            caption_url: The Zoom caption URL (provided by Zoom meeting host)
            http_client: Shared httpx async client
            lang: Optional language code (e.g., "ja", "en-US")
        """
        self._base_url = caption_url
        self._http_client = http_client
        self._lang = lang
        self._seq = 0

    def _build_url(self) -> str:
        """Build the URL with seq and optional lang parameters."""
        parsed = urlparse(self._base_url)
        query_params = parse_qs(parsed.query)
        
        # Add/update seq parameter
        query_params["seq"] = [str(self._seq)]
        
        # Add lang parameter if specified
        if self._lang:
            query_params["lang"] = [self._lang]
        
        # Rebuild query string (flatten lists)
        flat_params = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}
        new_query = urlencode(flat_params, doseq=True)
        
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))

    async def send_caption(self, text: str) -> bool:
        """Send caption text to Zoom.
        
        Args:
            text: The caption text to send
            
        Returns:
            True if successful, False otherwise
        """
        if not text.strip():
            return True
            
        url = self._build_url()
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        
        try:
            response = await self._http_client.post(
                url,
                content=text.encode("utf-8"),
                headers=headers,
            )
            
            if response.status_code == 200:
                self._seq += 1
                logger.debug("Caption sent successfully, seq=%d", self._seq)
                return True
            elif response.status_code == 400:
                logger.warning("Caption failed: bad request or meeting ended")
            elif response.status_code == 403:
                logger.warning("Caption failed: URL expired or invalid signature")
            elif response.status_code == 405:
                logger.warning("Caption failed: wrong HTTP method")
            else:
                logger.warning("Caption failed: status=%d", response.status_code)
                
            return False
            
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send caption to Zoom")
            return False

    async def get_last_seq(self) -> int | None:
        """Get the last successful sequence number from Zoom.
        
        Returns:
            The last successful seq number, or None if failed
        """
        parsed = urlparse(self._base_url)
        seq_path = parsed.path.replace("/closedcaption", "/closedcaption/seq")
        seq_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            seq_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
        
        try:
            response = await self._http_client.get(seq_url)
            if response.status_code == 200:
                return int(response.text.strip())
        except Exception:  # noqa: BLE001
            logger.exception("Failed to get last seq from Zoom")
        
        return None

    async def sync_seq(self) -> None:
        """Sync the internal seq counter with Zoom's last known seq."""
        last_seq = await self.get_last_seq()
        if last_seq is not None:
            self._seq = last_seq + 1
            logger.info("Synced seq to %d", self._seq)
