"""Restore the original request path on Vercel.

backend/vercel.json rewrites every request to the single Python function at /api/index, which
then receives "/api/index" as its path. The rewrite passes the original path along as the
``__path`` query parameter; this ASGI middleware puts it back before routing.
"""

from urllib.parse import parse_qsl, unquote, urlencode

FUNCTION_PATHS = {"/api/index", "/api/index.py"}
PARAM = "__path"


class VercelPathMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope.get("path") in FUNCTION_PATHS:
            pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
            original = next((v for k, v in pairs if k == PARAM), None)
            if original is not None:
                path = "/" + unquote(original).lstrip("/")
                scope = dict(scope)
                scope["path"] = path
                scope["raw_path"] = path.encode()
                scope["query_string"] = urlencode([(k, v) for k, v in pairs if k != PARAM]).encode("latin-1")
        await self.app(scope, receive, send)
