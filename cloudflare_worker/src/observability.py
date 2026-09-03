"""Structured logging so worker decisions are visible in logs and traces."""

import json


def log_event(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, default=str))
