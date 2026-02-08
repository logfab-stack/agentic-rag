"""
Ngrok API endpoints for auto-detecting ngrok tunnels and displaying webhook URLs.

This module queries the ngrok local API (http://127.0.0.1:4040/api/tunnels)
to detect running tunnels and provide webhook URLs for WhatsApp integration.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import httpx
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Ngrok local API endpoint (default)
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"


class NgrokTunnel(BaseModel):
    """Information about a single ngrok tunnel."""
    name: str
    public_url: str
    proto: str
    config_addr: str  # e.g., "http://localhost:8000"


class NgrokStatusResponse(BaseModel):
    """Response model for ngrok status check."""
    running: bool
    public_url: Optional[str] = None
    webhook_url: Optional[str] = None
    tunnels: list[NgrokTunnel] = []
    error: Optional[str] = None


@router.get("/status", response_model=NgrokStatusResponse)
async def get_ngrok_status():
    """
    Get the current ngrok tunnel status.

    Queries the ngrok local API at http://127.0.0.1:4040/api/tunnels
    to detect running tunnels and returns:
    - running: Whether ngrok is running
    - public_url: The public HTTPS URL (if found)
    - webhook_url: The full WhatsApp webhook URL ({public_url}/api/whatsapp/webhook)
    - tunnels: List of all detected tunnels
    - error: Error message if ngrok is not running or query failed
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(NGROK_API_URL)
            response.raise_for_status()

            data = response.json()
            tunnels_data = data.get("tunnels", [])

            if not tunnels_data:
                return NgrokStatusResponse(
                    running=True,
                    error="ngrok is running but no tunnels are active"
                )

            # Parse tunnels
            tunnels = []
            https_url = None

            for tunnel in tunnels_data:
                tunnel_info = NgrokTunnel(
                    name=tunnel.get("name", "unknown"),
                    public_url=tunnel.get("public_url", ""),
                    proto=tunnel.get("proto", ""),
                    config_addr=tunnel.get("config", {}).get("addr", "")
                )
                tunnels.append(tunnel_info)

                # Prefer HTTPS URL for webhook
                if tunnel.get("proto") == "https":
                    https_url = tunnel.get("public_url")

            # If no HTTPS tunnel, use the first available URL
            if not https_url and tunnels:
                https_url = tunnels[0].public_url

            # Build the full webhook URL
            webhook_url = f"{https_url}/api/whatsapp/webhook" if https_url else None

            logger.info(f"ngrok detected: {https_url}")
            logger.info(f"WhatsApp webhook URL: {webhook_url}")

            return NgrokStatusResponse(
                running=True,
                public_url=https_url,
                webhook_url=webhook_url,
                tunnels=tunnels
            )

    except httpx.ConnectError:
        logger.debug("ngrok is not running (connection refused)")
        return NgrokStatusResponse(
            running=False,
            error="ngrok is not running. Start it with: ngrok http 8000"
        )
    except httpx.TimeoutException:
        logger.warning("ngrok API request timed out")
        return NgrokStatusResponse(
            running=False,
            error="ngrok API request timed out"
        )
    except Exception as e:
        logger.error(f"Error checking ngrok status: {e}")
        return NgrokStatusResponse(
            running=False,
            error=f"Failed to check ngrok status: {str(e)}"
        )
