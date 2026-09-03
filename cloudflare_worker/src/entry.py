"""Worker entrypoint: request routing and bearer-token auth only.

Endpoint handlers live in callers.py, service_requests.py, scheduling.py,
notes.py, and seed.py. Commercial classification lives in commercial_services.py.
"""

from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from callers import handle_lookup, handle_remember
from dashboard import handle_dashboard, handle_emergency_queue
from service_requests import handle_service_request
from scheduling import (
    handle_availability,
    handle_book,
    handle_booking_lookup,
    handle_booking_update,
)
from notes import handle_note
from seed import handle_seed


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed_url = urlparse(request.url)
        path = parsed_url.path

        if path == "/health":
            return Response.json({"status": "OK"})

        if path in {"/", "/dashboard"} and request.method == "GET":
            local_token = (
                self.env.CUSTOMER_MEMORY_TOKEN
                if parsed_url.hostname in {"127.0.0.1", "localhost", "::1"}
                else None
            )
            return handle_dashboard(local_token)

        authorization = request.headers.get("authorization")
        expected_authorization = f"Bearer {self.env.CUSTOMER_MEMORY_TOKEN}"
        if authorization != expected_authorization:
            return Response.json({"error": "UNAUTHORIZED"}, status=401)

        if path == "/api/emergency-queue" and request.method == "GET":
            return await handle_emergency_queue(self.env)

        if request.method != "POST":
            return Response.json({"error": "METHOD_NOT_ALLOWED"}, status=405)

        try:
            body = await request.json()
        except ValueError:
            return Response.json({"error": "INVALID_JSON"}, status=400)

        if path == "/lookup":
            return await handle_lookup(self.env, body)
        if path == "/remember":
            return await handle_remember(self.env, body)
        if path == "/service-request":
            return await handle_service_request(self.env, body)
        if path == "/availability":
            return await handle_availability(self.env, body)
        if path == "/book":
            return await handle_book(self.env, body)
        if path == "/booking-lookup":
            return await handle_booking_lookup(self.env, body)
        if path == "/booking-update":
            return await handle_booking_update(self.env, body)
        if path == "/note":
            return await handle_note(self.env, body)
        if path == "/seed":
            return await handle_seed(self.env)

        return Response.json({"error": "NOT_FOUND"}, status=404)
