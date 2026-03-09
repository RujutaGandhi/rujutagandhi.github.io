#!/usr/bin/env python3
# Production threshold: 0.5 - chosen based on escalation test results showing 2/2 PASS only at 0.5
"""
agent.py

USPS customer service agent using Claude with tool use.

Tools:
  - search_usps_knowledge: semantic search over usps_content_multiqa in Supabase,
    using match_usps_multiqa RPC with match_threshold=0.5 and match_count=5,
    deduplicated by article title.
  - escalate_to_human: returns USPS contact options (phone, live chat, help page).

Agent behavior:
  - Embeds the user question with multi-qa-MiniLM-L6-cos-v1
  - Forces search_usps_knowledge on the first turn
  - Answers ONLY from retrieved content — never from Claude's training data
  - Cites source URL and article title in every answer
  - Auto-escalates when no results are found above threshold
  - Runs as an interactive CLI loop

Reads SUPABASE_URL, SUPABASE_ANON_KEY, and ANTHROPIC_API_KEY from .env
"""

import json
import os
import sys
from typing import Any, Dict, List

import anthropic
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MATCH_THRESHOLD  = 0.5                        # production threshold
MATCH_COUNT      = 5
EMBEDDING_MODEL  = "multi-qa-MiniLM-L6-cos-v1"
RPC_FUNCTION     = "match_usps_multiqa"
CLAUDE_MODEL     = "claude-sonnet-4-20250514"
MAX_TOKENS       = 512
TEMPERATURE      = 0.1

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a friendly USPS customer service assistant. Your goal is to help \
customers with their postal service questions quickly and clearly.

GROUNDEDNESS RULE — CRITICAL:
Answer ONLY using content retrieved from the USPS knowledge base via \
search_usps_knowledge. USPS policies, prices, and procedures change \
frequently — never rely on your training data. If the retrieved content \
does not contain the answer, do not guess.

WORKFLOW:
Always call search_usps_knowledge first before responding to any question.
After reviewing the results, either answer from the content or call \
escalate_to_human.

ESCALATION — call escalate_to_human if:
- No relevant content was found above the similarity threshold
- The question involves complaints, payments, account issues, or disputes
- You cannot confidently answer from the retrieved content

CITATIONS:
Every answer must include the source article title and URL from the \
search results. Format: "Source: <title> — <url>"

TONE:
Calm, concise, and plain language. Users may be frustrated — be \
empathetic and direct. Keep answers brief; avoid jargon.

SCOPE:
If the question is not related to USPS services, politely say it is \
outside your scope and offer to connect them with a USPS representative \
via escalate_to_human.

UNCERTAINTY:
If you are only partially confident in an answer based on the retrieved \
content, clearly state your uncertainty before providing the information.\
"""

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "search_usps_knowledge",
        "description": (
            "Search the USPS knowledge base for relevant articles. "
            "Always call this first before answering any question. "
            "Returns the most relevant USPS FAQ content with similarity "
            "scores, article titles, and source URLs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The customer's question or topic to search for.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate to a human USPS representative. Call this when: "
            "(1) no relevant knowledge base results were found, "
            "(2) the question involves complaints, payments, or account issues, "
            "(3) you cannot confidently answer from retrieved content, or "
            "(4) the question is outside USPS scope."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for escalation (shown to the customer).",
                }
            },
            "required": ["reason"],
        },
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def deduplicate(results: List[dict], keep: int) -> List[dict]:
    """Keep only the highest-scoring chunk per article title, up to `keep` articles."""
    seen_titles: set = set()
    deduped: List[dict] = []
    for row in results:
        title = row.get("title", "").lower().strip()
        if title not in seen_titles:
            seen_titles.add(title)
            deduped.append(row)
            if len(deduped) == keep:
                break
    return deduped


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def _search_usps_knowledge(
    query: str, supabase: Client, embedder: SentenceTransformer
) -> str:
    """Embed query, call Supabase RPC, deduplicate, return JSON string."""
    embedding: List[float] = embedder.encode([query], show_progress_bar=False).tolist()[0]

    params: Dict[str, Any] = {}
    params["query_embedding"] = embedding
    params["match_threshold"]  = MATCH_THRESHOLD
    params["match_count"]      = MATCH_COUNT

    try:
        resp = supabase.rpc(RPC_FUNCTION, params).execute()
        raw: List[dict] = resp.data or []
    except Exception as exc:
        return json.dumps({"found": False, "error": str(exc), "results": []})

    results = deduplicate(raw, keep=MATCH_COUNT)

    if not results:
        return json.dumps({
            "found": False,
            "message": (
                "No relevant USPS content found above the similarity threshold "
                f"({MATCH_THRESHOLD}). The question may be outside USPS scope "
                "or too ambiguous — consider escalating to a human."
            ),
            "results": [],
        })

    formatted = [
        {
            "title":      r.get("title", ""),
            "url":        r.get("url", ""),
            "similarity": round(r.get("similarity", 0.0), 3),
            "content":    r.get("content", ""),
        }
        for r in results
    ]
    return json.dumps({"found": True, "results": formatted})


def _escalate_to_human(reason: str) -> str:
    """Return structured USPS contact options for the agent to relay."""
    return json.dumps({
        "escalated": True,
        "reason": reason,
        "contact_options": {
            "phone":     "1-800-275-8777 (1-800-ASK-USPS), Mon–Fri 8 AM–8:30 PM ET, Sat 8 AM–6 PM ET",
            "live_chat": "https://www.usps.com/help/contact-us.htm",
            "help_page": "https://www.usps.com/help/welcome.htm",
        },
        "instruction": (
            "Inform the customer that you are escalating their question and "
            "provide all three contact options above."
        ),
    })


def execute_tool(
    name: str,
    tool_input: Dict[str, Any],
    supabase: Client,
    embedder: SentenceTransformer,
) -> str:
    if name == "search_usps_knowledge":
        return _search_usps_knowledge(tool_input["query"], supabase, embedder)
    if name == "escalate_to_human":
        return _escalate_to_human(tool_input.get("reason", ""))
    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_agent(
    question: str,
    client: anthropic.Anthropic,
    supabase: Client,
    embedder: SentenceTransformer,
) -> str:
    """Run the agentic loop for a single user question and return the answer."""
    messages: List[Dict[str, Any]] = [{"role": "user", "content": question}]

    # First call: force search_usps_knowledge so the agent always retrieves
    # before deciding whether to answer or escalate.
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        tool_choice={"type": "tool", "name": "search_usps_knowledge"},
        messages=messages,
    )

    # Agentic loop — continue while Claude is calling tools
    while response.stop_reason == "tool_use":
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        # Append assistant turn (including tool_use blocks)
        messages.append({"role": "assistant", "content": response.content})

        # Execute every requested tool and collect results
        tool_results = []
        for tool in tool_use_blocks:
            result_content = execute_tool(tool.name, tool.input, supabase, embedder)
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tool.id,
                "content":     result_content,
            })

        messages.append({"role": "user", "content": tool_results})

        # Next turn — Claude now decides to answer or call another tool
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

    # Extract the final text response
    return next(
        (b.text for b in response.content if b.type == "text"),
        "I'm sorry, I was unable to generate a response. Please contact USPS directly at 1-800-275-8777.",
    )


# ---------------------------------------------------------------------------
# Main — interactive CLI loop
# ---------------------------------------------------------------------------
def main() -> None:
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        sys.exit(1)
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY must be set in .env")
        sys.exit(1)

    print("Loading embedding model...")
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    print("  Done.")

    print("Connecting to Supabase...")
    supabase = create_client(supabase_url, supabase_key)
    print("  Connected.")

    claude = anthropic.Anthropic(api_key=anthropic_key)

    print("\n" + "=" * 60)
    print("  USPS Customer Service Agent")
    print(f"  Model: {CLAUDE_MODEL}  |  Threshold: {MATCH_THRESHOLD}")
    print("  Type 'quit' to exit.")
    print("=" * 60)

    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "bye", "q"):
            print("Goodbye!")
            break

        print("\nAgent: ", end="", flush=True)
        answer = run_agent(question, claude, supabase, embedder)
        print(answer)


if __name__ == "__main__":
    main()
