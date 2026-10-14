"""
Stdio Process Subprocess SSE Bridge Server for MCP.

Spawns the `google-finance-mcp` CLI command as a subprocess,
and forwards MCP JSON-RPC messages between HTTP SSE connections
and the subprocess stdio streams.

Supports optional AUTH_TOKEN authentication via HTTP Bearer token or ?token= query parameter.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import shutil
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

# Setup logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp-stdio-bridge")

SUBPROCESS_CMD = os.getenv("MCP_SUBPROCESS_CMD", "google-finance-mcp")
USE_SUBPROCESS = os.getenv("USE_SUBPROCESS", "true").lower() in ("true", "1", "yes")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "").strip()

sse = SseServerTransport("/messages/")


def _is_authenticated(request: Request) -> bool:
    """Validate Bearer token from Authorization header or ?token= query param if AUTH_TOKEN is set."""
    if not AUTH_TOKEN:
        return True

    # 1. Check Authorization header: 'Bearer <token>'
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if hmac.compare_digest(token, AUTH_TOKEN):
            return True

    # 2. Check query parameter '?token=<token>' (useful for SSE EventSource clients that cannot set headers)
    query_token = request.query_params.get("token", "")
    if query_token and hmac.compare_digest(query_token, AUTH_TOKEN):
        return True

    return False


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    logger.info("Initializing MCP SSE-to-Stdio Bridge Server...")
    if AUTH_TOKEN:
        logger.info("Authentication enabled (AUTH_TOKEN configured).")
    else:
        logger.warning("No AUTH_TOKEN set. The MCP SSE server endpoints are publicly accessible.")

    if USE_SUBPROCESS:
        cmd_path = shutil.which(SUBPROCESS_CMD)
        logger.info(f"Target command: '{SUBPROCESS_CMD}' (resolved: {cmd_path})")
        if not cmd_path:
            logger.warning(
                f"Command '{SUBPROCESS_CMD}' not found on PATH. Ensure package is installed into environment."
            )
    yield
    logger.info("Shutting down MCP SSE-to-Stdio Bridge Server...")


async def _bridge_stdio_subprocess(read_stream, write_stream):
    """
    Spawns `google-finance-mcp` and bridges MCP Session messages with subprocess stdin/stdout.
    """
    logger.info(f"Spawning subprocess: {SUBPROCESS_CMD}")
    process = await anyio.open_process(
        [SUBPROCESS_CMD],
        stdin=anyio.subprocess.PIPE,
        stdout=anyio.subprocess.PIPE,
        stderr=sys.stderr,
    )

    async def forward_client_to_process():
        try:
            async for message in read_stream:
                if hasattr(message, "model_dump_json"):
                    payload = message.model_dump_json(by_alias=True, exclude_none=True)
                elif isinstance(message, dict):
                    payload = json.dumps(message)
                else:
                    payload = str(message)

                if process.stdin:
                    await process.stdin.send(f"{payload}\n".encode("utf-8"))
        except anyio.get_cancelled_exc_class():
            pass
        except Exception as e:
            logger.error(f"Error forwarding client message to subprocess: {e}")
        finally:
            if process.stdin:
                await process.stdin.aclose()

    async def forward_process_to_client():
        try:
            if not process.stdout:
                return
            buffer = ""
            async for chunk in process.stdout:
                buffer += chunk.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        await write_stream.send(data)
                    except json.JSONDecodeError as err:
                        logger.warning(f"Non-JSON line received from subprocess: {line} ({err})")
        except anyio.get_cancelled_exc_class():
            pass
        except Exception as e:
            logger.error(f"Error forwarding subprocess stdout to client: {e}")

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(forward_client_to_process)
            tg.start_soon(forward_process_to_client)
            await process.wait()
            tg.cancel_scope.cancel()
    finally:
        try:
            process.terminate()
            await process.wait()
        except ProcessLookupError:
            pass


async def _run_in_process(read_stream, write_stream):
    """Fallback direct in-process server dispatch."""
    from google_finance_mcp.server import server as gf_server
    await gf_server.run(
        read_stream,
        write_stream,
        gf_server.create_initialization_options(),
    )


async def handle_sse(request: Request) -> Response:
    """Handle incoming SSE connections from MCP clients."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Unauthorized: Invalid or missing AUTH_TOKEN"}, status_code=401)

    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        if USE_SUBPROCESS:
            await _bridge_stdio_subprocess(read_stream, write_stream)
        else:
            await _run_in_process(read_stream, write_stream)
    return Response(status_code=200)


async def handle_messages(request: Request) -> Response:
    """Handle incoming client JSON-RPC messages routed via SSE transport."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Unauthorized: Invalid or missing AUTH_TOKEN"}, status_code=401)

    await sse.handle_post_message(request.scope, request.receive, request._send)
    return Response(status_code=202)


async def handle_health(request: Request) -> JSONResponse:
    """Health check endpoint for Dokploy / Docker health checks."""
    return JSONResponse(
        {
            "status": "healthy",
            "server": "google-finance-mcp",
            "auth_required": bool(AUTH_TOKEN),
            "mode": "subprocess" if USE_SUBPROCESS else "in-process",
            "endpoints": {
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
    logger.info(f"Serving Google Finance MCP on http://{host}:{port}/sse")
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())
