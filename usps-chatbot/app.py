#!/usr/bin/env python3
"""
app.py  —  USPS Chatbot V2

FastAPI wrapper around agent.py for deployment on Render.

Changes from V1:
  - POST /chat now returns a streaming SSE response instead of a JSON blob.
    Tokens stream as Claude generates them; a final [DONE] event carries metadata.
  - ChatRequest now accepts conversation_history and turn_number from the frontend.
  - ChatResponse model retained for documentation; actual wire format is SSE.

SSE event format:
    Each chunk:   data: {"type": "token", "text": "<chunk>"}\n\n
    Final event:  data: {"type": "done", "source_title": ..., "source_url": ...,
                          "similarity_score": ..., "escalated": bool,
                          "needs_clarification": bool}\n\n
    On error:     data: {"type": "error", "message": "<msg>"}\n\n

Endpoints:
  POST /chat   — streaming SSE response
  GET  /health — {"status": "ok"} for keep-alive pings

Reads SUPABASE_URL, SUPABASE_ANON_KEY, ANTHROPIC_API_KEY, VOYAGEAI_API_KEY from .env
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

import anthropic
import uvicorn
import voyageai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from supabase import create_client, Client

from agent import run_agent_stream, VOYAGE_MODEL, CLAUDE_MODEL, MATCH_THRESHOLD

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question:             str  = Field(..., min_length=1, max_length=1000)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    turn_number:          int  = Field(default=1, ge=1)


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
class AppState:
    vo:       voyageai.Client
    supabase: Client
    claude:   anthropic.Anthropic


state = AppState()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()

    supabase_url  = os.getenv("SUPABASE_URL")
    supabase_key  = os.getenv("SUPABASE_ANON_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    voyage_key    = os.getenv("VOYAGEAI_API_KEY")

    missing = [
        name for name, val in [
            ("SUPABASE_URL",      supabase_url),
            ("SUPABASE_ANON_KEY", supabase_key),
            ("ANTHROPIC_API_KEY", anthropic_key),
            ("VOYAGEAI_API_KEY",  voyage_key),
        ]
        if not val
    ]
    if missing:
        print(f"ERROR: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to Voyage AI ({VOYAGE_MODEL})...")
    state.vo = voyageai.Client(api_key=voyage_key)
    print("  Done.")

    print("Connecting to Supabase...")
    state.supabase = create_client(supabase_url, supabase_key)
    print("  Connected.")

    state.claude = anthropic.Anthropic(api_key=anthropic_key)
    print(f"USPS agent V2 ready  |  model: {CLAUDE_MODEL}  |  threshold: {MATCH_THRESHOLD}")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="USPS Customer Service Agent V2",
    description="Streaming RAG chatbot — Claude + Voyage AI + Supabase pgvector.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------
def sse(payload: Dict[str, Any]) -> str:
    """Format a dict as a single SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


async def stream_chat(request: ChatRequest) -> AsyncGenerator[str, None]:
    """
    Async generator that drives run_agent_stream and yields SSE strings.

    run_agent_stream is a synchronous generator (it uses the blocking Anthropic
    SDK). We iterate it directly — FastAPI / Starlette handle the async bridging
    via StreamingResponse with a sync generator fallback, but yielding from an
    async generator keeps the event loop free between chunks.
    """
    try:
        # run_agent_stream is a sync generator; iterate it and yield SSE lines
        for event in run_agent_stream(
            question=request.question,
            client=state.claude,
            supabase=state.supabase,
            vo=state.vo,
            conversation_history=request.conversation_history or [],
            turn_number=request.turn_number,
        ):
            yield sse(event)

    except anthropic.AuthenticationError:
        yield sse({"type": "error", "message": "Claude API authentication failed."})
    except anthropic.RateLimitError:
        yield sse({"type": "error", "message": "Rate limit reached. Please try again shortly."})
    except anthropic.APIConnectionError:
        yield sse({"type": "error", "message": "Could not reach the Claude API. Please try again."})
    except anthropic.APIStatusError as exc:
        yield sse({"type": "error", "message": f"Claude API error: {exc.message}"})
    except Exception as exc:
        yield sse({"type": "error", "message": f"Internal error: {str(exc)}"})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Health check / keep-alive ping."""
    return HealthResponse(status="ok")


@app.post("/chat", tags=["agent"])
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Process a USPS customer service question and stream the response via SSE.

    The client should read the stream and handle three event types:
      - token: append text to the message bubble
      - done:  mark the message complete, store metadata (source URL etc.)
      - error: display an error message to the user
    """
    return StreamingResponse(
        stream_chat(request),
        media_type="text/event-stream",
        headers={
            # Prevent proxies / Render from buffering the stream
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000, reload=False)
