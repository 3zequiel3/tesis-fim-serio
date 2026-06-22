"""
Middleware CORS con validación de Origin contra whitelist (RN-95, D7).

Si el header Origin está presente y NO está en CORS_ALLOWED_ORIGINS → 403.
Si Origin no está presente (curl, servicios internos) → la request pasa.
Si Origin está en la whitelist → agrega Access-Control-Allow-Origin a la response.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


_CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Requested-With",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Max-Age": "600",
}


class CORSOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        origin = request.headers.get("origin")

        if origin is not None:
            allowed = settings.get_allowed_origins()
            if origin not in allowed:
                return Response(
                    content='{"detail":"CORS origin not allowed"}',
                    status_code=403,
                    media_type="application/json",
                )

            # Preflight OPTIONS — responder directamente sin llegar al endpoint
            if request.method == "OPTIONS":
                headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin", **_CORS_HEADERS}
                return Response(status_code=204, headers=headers)

        response = await call_next(request)

        if origin is not None:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            for k, v in _CORS_HEADERS.items():
                response.headers[k] = v

        return response
