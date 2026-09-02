"""Concern notes: feedback or complaints recorded without an appointment."""

import json
import uuid
from datetime import datetime, timezone

from workers import Response


async def handle_note(env, body: dict):
    note = str(body.get("note", "")).strip()
    if not note:
        return Response.json({"error": "NOTE_REQUIRED"}, status=400)

    note_id = f"note-{uuid.uuid4().hex[:8]}"
    record = {
        "note_id": note_id,
        "note": note,
        "name": str(body.get("name", "")).strip(),
        "contact": str(body.get("contact", "")).strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await env.CALLERS.put(f"note:{note_id}", json.dumps(record))
    return Response.json({"saved": True, **record})
