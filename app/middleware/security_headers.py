"""
Security headers middleware.

Adds a conservative set of response headers to every request. These are cheap,
broadly compatible defaults that reduce common web risks (MIME sniffing,
clickjacking, referrer leakage). HSTS is only emitted when the request arrived
over HTTPS so local HTTP development is unaffected.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _STATIC_HEADERS.items():
            response.headers.setdefault(header, value)
        # Only assert HSTS when the connection is actually secure.
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
