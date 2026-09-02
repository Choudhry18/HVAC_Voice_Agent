import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint


def normalize_phone_number(phone_number: str) -> str:
    digits = "".join(character for character in phone_number if character.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    return f"+{digits}" if digits else ""


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(request.url).path

        if path == "/health":
            return Response.json({"status": "OK"})

        authorization = request.headers.get("authorization")
        expected_authorization = f"Bearer {self.env.CUSTOMER_MEMORY_TOKEN}"
        if authorization != expected_authorization:
            return Response.json({"error": "UNAUTHORIZED"}, status=401)

        if request.method != "POST":
            return Response.json({"error": "METHOD_NOT_ALLOWED"}, status=405)

        try:
            body = await request.json()
        except ValueError:
            return Response.json({"error": "INVALID_JSON"}, status=400)

        phone_number = normalize_phone_number(str(body.get("phone_number", "")))
        if not phone_number:
            return Response.json({"error": "PHONE_NUMBER_REQUIRED"}, status=400)

        key = f"caller:{phone_number}"

        if path == "/lookup":
            stored_record = await self.env.CALLERS.get(key)
            if not stored_record:
                return Response.json(
                    {"found": False, "phone_number": phone_number}
                )
            return Response.json({"found": True, **json.loads(stored_record)})

        if path == "/remember":
            name = str(body.get("name", "")).strip()
            previous_request = str(body.get("previous_request", "")).strip()
            address = str(body.get("address", "")).strip()
            if not name or not previous_request:
                return Response.json(
                    {"error": "NAME_AND_REQUEST_REQUIRED"}, status=400
                )

            record = {
                "phone_number": phone_number,
                "name": name,
                "previous_request": previous_request,
                "address": address,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.env.CALLERS.put(key, json.dumps(record))
            return Response.json({"saved": True, **record})

        return Response.json({"error": "NOT_FOUND"}, status=404)
