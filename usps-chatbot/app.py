#!/usr/bin/env python3
"""
app.py

FastAPI wrapper around agent.py for deployment on Render.

Endpoints:
  POST /chat   — accepts {"question": str}, returns structured agent response
  GET  /health — returns {"status": "ok"} for health checks / keep-alive pings

Clients (Supabase, Anthropic, Voyage AI) are initialised once at
startup and reused across requests.

Reads SUPABASE_URL, SUPABASE_ANON_KEY, ANTHROPIC_API_KEY, and VOYAGEAI_API_KEY from .env
"""

import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

import anthropic
import uvicorn
import voyageai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

from agent import run_agent, VOYAGE_MODEL, CLAUDE_MODEL, MATCH_THRESHOLD

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    answer:           str
    source_title:     Optional[str]  = None
    source_url:       Optional[str]  = None
    similarity_score: Optional[float] = None
    escalated:        bool           = False


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Application state — populated at startup
# ---------------------------------------------------------------------------
class AppState:
    vo:       voyageai.Client
    supabase: Client
    claude:   anthropic.Anthropic


state = AppState()


# ---------------------------------------------------------------------------
# Lifespan — initialise clients once at startup
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

    print(f"USPS agent ready  |  model: {CLAUDE_MODEL}  |  threshold: {MATCH_THRESHOLD}")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="USPS Customer Service Agent",
    description="Semantic search over USPS FAQ content, powered by Claude.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Health check / keep-alive ping."""
    return HealthResponse(status="ok")


@app.post("/chat", response_model=ChatResponse, tags=["agent"])
def chat(request: ChatRequest) -> ChatResponse:
    """
    Process a USPS customer service question.

    - Searches the USPS knowledge base using semantic similarity.
    - Answers from retrieved content only; escalates when no relevant
      content is found or the question is outside USPS scope.
    """
    try:
        result = run_agent(
            question=request.question,
            client=state.claude,
            supabase=state.supabase,
            vo=state.vo,
        )
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=500, detail="Claude API authentication failed.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Claude API rate limit reached. Please try again shortly.")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=503, detail="Could not reach the Claude API. Please try again.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc.message}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(exc)}")

    return ChatResponse(
        answer=result["answer"],
        source_title=result.get("source_title"),
        source_url=result.get("source_url"),
        similarity_score=result.get("similarity_score"),
        escalated=result.get("escalated", False),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000, reload=False)
