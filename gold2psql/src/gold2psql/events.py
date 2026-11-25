import json
import time
from datetime import datetime, timezone

import pika


class EventError(RuntimeError):
    pass


def publish(url: str, queue: str, body: bytes) -> None:
    """Publish one persistent message to `queue` (default exchange) and wait for the broker's confirm."""
    with pika.BlockingConnection(pika.URLParameters(url)) as conn:
        ch = conn.channel()
        ch.queue_declare(queue=queue, durable=True)
        ch.confirm_delivery()
        ch.basic_publish(
            exchange="", routing_key=queue, body=body, mandatory=True,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )


def send_event(publisher, url: str, queue: str, payload: dict, retries: int,
               retry_delay_seconds: float, sleep=time.sleep) -> int:
    """Publish with up to `retries` retries after the first attempt; returns attempts used."""
    body = json.dumps({**payload, "sent_at": datetime.now(timezone.utc).isoformat()}).encode()
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            publisher(url, queue, body)
            return attempt
        except Exception as e:  # any broker/network failure is retryable
            if attempt == attempts:
                raise EventError(f"event to {queue!r} failed after {attempts} attempts: {e}") from e
            sleep(retry_delay_seconds * attempt)  # linear backoff
