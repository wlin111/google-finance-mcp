"""
Stdio Process Subprocess SSE Bridge Server for MCP.

Spawns the `google-finance-mcp` CLI command as a subprocess,
and forwards MCP JSON-RPC messages between HTTP SSE connections
and the subprocess stdio streams.
"""

from __future__ import annotations

import anyio
from anyio.streams.text import TextReceiveStream, TextSendStream
import json
import logging
import os
import shutil
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

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

# Fallback: Prefer in-process server instance if available, or subprocess execution.
# This script supports both pure stdio subprocess bridging and native in-process transport.
USE_SUBPROCESS = os.getenv("USE_SUBPROCESS", "true").lower() in ("true", "1", "yes")

sse = SseServerTransport("/messages/")


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    logger.info("Initializing MCP SSE-to-Stdio Bridge Server...")
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
                # message is JSON-RPC object or pydantic model; serialize to line-delimited JSON
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
    """Fallback / high-performance direct in-process server dispatch."""
    from google_finance_mcp.server import server as gf_server
    await gf_server.run(
        read_stream,
        write_stream,
        gf_server.create_initialization_options(),
    )


async def handle_sse(request: Request) -> Response:
    """Handle incoming SSE connections from MCP clients."""
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
    await sse.handle_post_message(request.scope, request.receive, request._send)
    return Response(status_code=202)


async def handle_health(request: Request) -> JSONResponse:
    """Health check endpoint for Dokploy / Docker health checks."""
    return JSONResponse(
        {
            "status": "healthy",
            "server": "google-finance-mcp",
            "mode": "subprocess" if USE_SUBPROCESS else "in-process",
            "cmd": SUBPROCESS_CMD if USE_SUBPROCESS else "direct",
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
