import json

import pytest

from gold2psql.events import EventError, send_event
from gold2psql.masking import build_masker

NAMES = ["id", "email", "name", "amount"]
TYPES = {"id": "INTEGER", "email": "VARCHAR", "name": "VARCHAR", "amount": "DECIMAL(12,2)"}


def masker(masking):
    return build_masker(NAMES, TYPES, ("id",), masking)


def test_no_masking_returns_none():
    assert masker({}) is None


def test_sequential_uses_pk_and_keeps_emails_email_shaped():
    m = masker({"email": "sequential", "name": "sequential"})
    assert m((7, "real@corp.com", "Real Person", 1)) == (7, "email_7@example.com", "name_7", 1)


def test_hash_is_deterministic_and_hides_value():
    m = masker({"email": "hash"})
    a, b = m((1, "a@b.com", "n", 1)), m((2, "a@b.com", "n", 1))
    assert a[1] == b[1] and "a@b.com" not in a[1] and a[1].endswith("@example.com")
    assert m((1, "other@b.com", "n", 1))[1] != a[1]


def test_null_strategy_and_null_passthrough():
    m = masker({"email": "null", "name": "hash"})
    assert m((1, "a@b.com", None, 1)) == (1, None, None, 1)


@pytest.mark.parametrize("masking,match", [
    ({"nope": "hash"}, "not found"),
    ({"amount": "hash"}, "VARCHAR"),
])
def test_invalid_masking(masking, match):
    with pytest.raises(ValueError, match=match):
        masker(masking)


def test_sequential_needs_integer_pk():
    m = build_masker(["id", "email"], {"id": "VARCHAR", "email": "VARCHAR"}, ("id",), {"email": "sequential"})
    with pytest.raises(ValueError, match="integer primary key"):
        m(("abc", "a@b.com"))
    with pytest.raises(ValueError, match="single-column"):
        build_masker(["a", "b", "e"], {"a": "INTEGER", "b": "INTEGER", "e": "VARCHAR"}, ("a", "b"),
                     {"e": "sequential"})


def test_event_retries_then_succeeds():
    calls, sleeps = [], []

    def flaky(url, queue, body):
        calls.append((url, queue, json.loads(body)))
        if len(calls) < 3:
            raise ConnectionError("down")

    attempts = send_event(flaky, "amqp://x", "q", {"table": "t", "rows": 5}, retries=3,
                          retry_delay_seconds=2, sleep=sleeps.append)
    assert attempts == 3 and sleeps == [2, 4]
    assert calls[-1][1] == "q" and calls[-1][2]["table"] == "t" and "sent_at" in calls[-1][2]


def test_event_gives_up_after_retries():
    calls = []

    def always_down(url, queue, body):
        calls.append(1)
        raise ConnectionError("down")

    with pytest.raises(EventError, match="4 attempts"):
        send_event(always_down, "amqp://x", "q", {}, retries=3, retry_delay_seconds=0, sleep=lambda s: None)
    assert len(calls) == 4


def test_zero_retries_means_one_attempt():
    calls = []

    def down(url, queue, body):
        calls.append(1)
        raise ConnectionError("down")

    with pytest.raises(EventError):
        send_event(down, "amqp://x", "q", {}, retries=0, retry_delay_seconds=0, sleep=lambda s: None)
    assert len(calls) == 1
