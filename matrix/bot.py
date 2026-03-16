from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx
from nio import AsyncClient, MatrixRoom, RoomMessageText
from pydantic_settings import BaseSettings, SettingsConfigDict


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("synapse-matrix")


class Settings(BaseSettings):
    # Matrix
    matrix_homeserver: str
    matrix_user_id: str
    matrix_access_token: str
    matrix_room_id: str

    # Synapse API (reachable from this container)
    api_base_url: str = "http://api:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


@dataclass(frozen=True)
class CaptureResult:
    memory_id: str
    category: str | None
    confidence: float | None


async def capture_thought(content: str, source: str) -> CaptureResult:
    url = f"{settings.api_base_url}/capture"
    payload = {"content": content, "source": source}

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    classification = data.get("classification")
    category = None
    confidence = None
    if isinstance(classification, dict):
        cat = classification.get("category")
        conf = classification.get("confidence")
        if isinstance(cat, str):
            category = cat
        if isinstance(conf, (int, float)):
            confidence = float(conf)

    mid = str(data.get("id"))
    return CaptureResult(memory_id=mid, category=category, confidence=confidence)


async def main() -> None:
    client = AsyncClient(settings.matrix_homeserver, settings.matrix_user_id)
    client.access_token = settings.matrix_access_token

    async def on_message(room: MatrixRoom, event: RoomMessageText) -> None:
        if room.room_id != settings.matrix_room_id:
            return
        if event.sender == settings.matrix_user_id:
            return

        body = (event.body or "").strip()
        if not body:
            return

        source = f"matrix:{room.room_id}:{event.sender}"
        try:
            res = await capture_thought(body, source)
            if res.category is not None and res.confidence is not None:
                msg = f"Stored: {res.memory_id} (category={res.category}, confidence={res.confidence:.2f})"
            else:
                msg = f"Stored: {res.memory_id}"
        except Exception as e:
            msg = f"Failed to store memory: {e}"

        await client.room_send(
            room_id=room.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": msg},
        )

    client.add_event_callback(on_message, RoomMessageText)

    log.info("Starting Matrix sync for room %s", settings.matrix_room_id)

    try:
        while True:
            try:
                await client.sync(timeout=30000)
            except Exception as e:
                log.warning("sync error: %s", e)
                await asyncio.sleep(2)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
