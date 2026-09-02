"""Worker entrypoint: request routing and bearer-token auth only.

Endpoint handlers live in callers.py (customer memory), scheduling.py
(availability and booking), and seed.py (mock data).
"""

from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from callers import handle_lookup, handle_remember
from scheduling import handle_availability, handle_book
from seed import handle_seed


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

        if path == "/lookup":
            return await handle_lookup(self.env, body)
        if path == "/remember":
            return await handle_remember(self.env, body)
        if path == "/availability":
            return await handle_availability(self.env, body)
        if path == "/book":
            return await handle_book(self.env, body)
        if path == "/seed":
            return await handle_seed(self.env)

        return Response.json({"error": "NOT_FOUND"}, status=404)
