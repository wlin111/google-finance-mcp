"""
Streamable HTTP & SSE Remote Server for Google Finance MCP.

Serves Google Finance MCP over:
1. Streamable HTTP (Modern MCP Standard at `/mcp` via StreamableHTTPSessionManager)
2. SSE Transport (Legacy compatibility at `/sse` & `/messages/`)
3. Health check at `/health`

Supports optional AUTH_TOKEN authentication via HTTP Bearer token or ?token= query parameter.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

# Setup logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp-server")

AUTH_TOKEN = os.getenv("AUTH_TOKEN", "").strip()

# Import the Google Finance MCP server instance
try:
    from google_finance_mcp.server import server as mcp_server
except ImportError:
    logger.error("google_finance_mcp package not found. Ensure it is installed in the python environment.")
    raise

# Try importing StreamableHTTPSessionManager (official MCP Python SDK >= 1.7 / modern standard)
try:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    HAS_STREAMABLE_HTTP = True
except ImportError:
    StreamableHTTPSessionManager = None  # type: ignore
    HAS_STREAMABLE_HTTP = False

# Import legacy SSE transport
try:
    from mcp.server.sse import SseServerTransport
    sse_transport = SseServerTransport("/messages/")
    HAS_SSE = True
except ImportError:
    sse_transport = None  # type: ignore
    HAS_SSE = False

# Initialize Streamable HTTP manager if supported
streamable_manager: StreamableHTTPSessionManager | None = None
if HAS_STREAMABLE_HTTP and StreamableHTTPSessionManager is not None:
    try:
        streamable_manager = StreamableHTTPSessionManager(
            app=mcp_server,
            stateless=True,
            json_response=True,
        )
    except TypeError:
        # Fallback for earlier parameter signature
        streamable_manager = StreamableHTTPSessionManager(app=mcp_server)


def _is_authenticated(scope: Scope, headers: dict[bytes, bytes], query_string: bytes) -> bool:
    """Validate Bearer token or ?token= query param if AUTH_TOKEN is set."""
    if not AUTH_TOKEN:
        return True

    # 1. Check Authorization header: 'Bearer <token>'
    auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="replace").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if hmac.compare_digest(token, AUTH_TOKEN):
            return True

    # 2. Check query parameter '?token=<token>'
    if query_string:
        from urllib.parse import parse_qs
        params = parse_qs(query_string.decode("utf-8", errors="replace"))
        tokens = params.get("token", [])
        if tokens and hmac.compare_digest(tokens[0], AUTH_TOKEN):
            return True

    return False


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    logger.info("Initializing Google Finance MCP Server...")
    if AUTH_TOKEN:
        logger.info("Authentication enabled (AUTH_TOKEN configured).")
    else:
        logger.warning("No AUTH_TOKEN set. The MCP server endpoints are publicly accessible.")

    if streamable_manager is not None:
        async with streamable_manager.run():
            logger.info("Streamable HTTP transport listening on /mcp")
            yield
    else:
        yield
    logger.info("Shutting down Google Finance MCP Server...")


async def handle_streamable_mcp(scope: Scope, receive: Receive, send: Send) -> None:
    """ASGI handler for Streamable HTTP endpoint /mcp."""
    headers = dict(scope.get("headers", []))
    query_string = scope.get("query_string", b"")

    if not _is_authenticated(scope, headers, query_string):
        response = JSONResponse({"error": "Unauthorized: Invalid or missing AUTH_TOKEN"}, status_code=401)
        await response(scope, receive, send)
        return

    if streamable_manager is None:
        response = JSONResponse({"error": "Streamable HTTP is not available in installed mcp version"}, status_code=501)
        await response(scope, receive, send)
        return

    await streamable_manager.handle_request(scope, receive, send)


async def handle_sse(request: Request) -> Response:
    """Handle incoming SSE connections from legacy MCP clients."""
    headers = dict(request.scope.get("headers", []))
    query_string = request.scope.get("query_string", b"")
    if not _is_authenticated(request.scope, headers, query_string):
        return JSONResponse({"error": "Unauthorized: Invalid or missing AUTH_TOKEN"}, status_code=401)

    if not HAS_SSE or sse_transport is None:
        return JSONResponse({"error": "SSE transport not available"}, status_code=501)

    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )
    return Response(status_code=200)


async def handle_messages(request: Request) -> Response:
    """Handle incoming client JSON-RPC messages routed via legacy SSE transport."""
    headers = dict(request.scope.get("headers", []))
    query_string = request.scope.get("query_string", b"")
    if not _is_authenticated(request.scope, headers, query_string):
        return JSONResponse({"error": "Unauthorized: Invalid or missing AUTH_TOKEN"}, status_code=401)

    if not HAS_SSE or sse_transport is None:
        return JSONResponse({"error": "SSE transport not available"}, status_code=501)

    await sse_transport.handle_post_message(request.scope, request.receive, request._send)
    return Response(status_code=202)


async def handle_health(request: Request) -> JSONResponse:
    """Health check endpoint for Dokploy / Docker health checks."""
    return JSONResponse(
        {
            "status": "healthy",
            "server": "google-finance-mcp",
            "auth_required": bool(AUTH_TOKEN),
            "transports": {
                "streamable_http": "/mcp" if HAS_STREAMABLE_HTTP else None,
                "sse": "/sse" if HAS_SSE else None,
            },
            "endpoints": {
                "streamable_http": "/mcp",
                "sse": "/sse",
                "messages": "/messages/",
                "health": "/health",
            },
        }
    )


routes = [
    Route("/health", endpoint=handle_health, methods=["GET"]),
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Route("/messages/", endpoint=handle_messages, methods=["POST"]),
    Mount("/mcp", app=handle_streamable_mcp),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(
    debug=os.getenv("DEBUG", "false").lower() == "true",
    routes=routes,
    middleware=middleware,
    lifespan=lifespan,
)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "3000"))
    logger.info(f"Serving Google Finance MCP on http://{host}:{port}/mcp (Streamable HTTP)")
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())
