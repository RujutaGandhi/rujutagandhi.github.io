#!/usr/bin/env python3
# Production threshold: 0.5 - chosen based on escalation test results showing 2/2 PASS only at 0.5
"""
agent.py

USPS customer service agent using Claude with tool use.

Tools:
  - search_usps_knowledge: semantic search over usps_content_voyage in Supabase,
    using match_usps_voyage RPC with match_threshold=0.5 and match_count=5,
    deduplicated by article title.
  - escalate_to_human: returns USPS contact options (phone, live chat, help page).

Agent behavior:
  - Embeds the user question with Voyage AI API (voyage-lite-02-instruct)
  - Forces search_usps_knowledge on the first turn
  - Answers ONLY from retrieved content — never from Claude's training data
  - Cites source URL and article title in every answer
  - Auto-escalates when no results are found above threshold
  - Runs as an interactive CLI loop

Reads SUPABASE_URL, SUPABASE_ANON_KEY, ANTHROPIC_API_KEY, and VOYAGEAI_API_KEY from .env
"""

import json
import os
import sys
from typing import Any, Dict, List

import anthropic
import voyageai
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MATCH_THRESHOLD = 0.3
MATCH_COUNT     = 5
VOYAGE_MODEL    = "voyage-3"
RPC_FUNCTION    = "match_usps_voyage"
CLAUDE_MODEL    = "claude-sonnet-4-20250514"
MAX_TOKENS      = 512
TEMPERATURE     = 0.1

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

FORMATTING:
Plain text only. No markdown, no bullet points, no bold, no numbered lists. \
Write in 3-4 natural sentences maximum. Then on a new line add: \
"For more details: <source_url>" — only if a source URL is available from \
the retrieved content. If no relevant content was found, follow the \
escalation instructions above.

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
    query: str, supabase: Client, vo: voyageai.Client
) -> str:
    """Embed query via Voyage API, call Supabase RPC, deduplicate, return JSON string."""
    try:
        result = vo.embed([query], model=VOYAGE_MODEL, input_type="query")
        embedding: List[float] = result.embeddings[0]
    except Exception as e:
        return json.dumps({"found": False, "error": f"Embedding failed: {str(e)}", "results": []})

    params: Dict[str, Any] = {
        "query_embedding": embedding,
        "match_threshold":  MATCH_THRESHOLD,
        "match_count":      MATCH_COUNT,
    }

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
    vo: voyageai.Client,
) -> str:
    if name == "search_usps_knowledge":
        return _search_usps_knowledge(tool_input["query"], supabase, vo)
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
    vo: voyageai.Client,
) -> Dict[str, Any]:
    """Run the agentic loop for a single user question.

    Returns a dict with keys:
        answer           (str)
        source_title     (str | None)
        source_url       (str | None)
        similarity_score (float | None)
        escalated        (bool)
    """
    messages: List[Dict[str, Any]] = [{"role": "user", "content": question}]

    meta: Dict[str, Any] = {
        "source_title":     None,
        "source_url":       None,
        "similarity_score": None,
        "escalated":        False,
    }

    # First call: force search_usps_knowledge
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        tool_choice={"type": "tool", "name": "search_usps_knowledge"},
        messages=messages,
    )

    # Agentic loop
    while response.stop_reason == "tool_use":
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool in tool_use_blocks:
            result_content = execute_tool(tool.name, tool.input, supabase, vo)

            try:
                result_data = json.loads(result_content)
                if tool.name == "search_usps_knowledge":
                    if result_data.get("found") and result_data.get("results"):
                        top = result_data["results"][0]
                        meta["source_title"]     = top.get("title")
                        meta["source_url"]       = top.get("url")
                        meta["similarity_score"] = top.get("similarity")
                elif tool.name == "escalate_to_human":
                    meta["escalated"] = True
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tool.id,
                "content":     result_content,
            })

        messages.append({"role": "user", "content": tool_results})

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

    answer = next(
        (b.text for b in response.content if b.type == "text"),
        "I'm sorry, I was unable to generate a response. Please contact USPS directly at 1-800-275-8777.",
    )
    return {"answer": answer, **meta}


# ---------------------------------------------------------------------------
# Main — interactive CLI loop
# ---------------------------------------------------------------------------
def main() -> None:
    load_dotenv()

    supabase_url  = os.getenv("SUPABASE_URL")
    supabase_key  = os.getenv("SUPABASE_ANON_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    voyage_key    = os.getenv("VOYAGEAI_API_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        sys.exit(1)
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY must be set in .env")
        sys.exit(1)
    if not voyage_key:
        print("ERROR: VOYAGEAI_API_KEY must be set in .env")
        sys.exit(1)

    print("Connecting to Voyage AI...")
    vo = voyageai.Client(api_key=voyage_key)
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
        result = run_agent(question, claude, supabase, vo)
        print(result["answer"])


if __name__ == "__main__":
    main()
