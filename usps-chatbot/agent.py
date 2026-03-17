#!/usr/bin/env python3
"""
agent.py  —  USPS Chatbot V2

Changes from V1:
  - conversation_history: last 3 exchanges (6 messages) passed into every Claude call
  - turn_number: client-supplied; on turn >= 4 skip retrieval and return empathetic escalation
  - summarization: system prompt instructs Claude to answer strictly under 100 words, MAX_TOKENS=125
  - clarifying question: pre-flight classifier runs before the agent loop;
    if the topic is ambiguous it returns a clarifying question immediately,
    skipping retrieval entirely. Never asks for personal data (tracking numbers etc.)
  - escalation message: warm, empathetic tone with phone + link

Tools:
  - search_usps_knowledge: semantic search over usps_content_voyage in Supabase
  - escalate_to_human: returns USPS contact options

Reads SUPABASE_URL, SUPABASE_ANON_KEY, ANTHROPIC_API_KEY, VOYAGEAI_API_KEY from .env
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

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
MAX_TOKENS      = 125   # hard ceiling — ~90-95 words at 0.75 words/token
TEMPERATURE     = 0.1
MAX_TURNS       = 3     # escalate on turn > MAX_TURNS

# ---------------------------------------------------------------------------
# Escalation message — empathetic, shown when turn limit is reached
# ---------------------------------------------------------------------------
TURN_LIMIT_MESSAGE = (
    "I've been glad to help so far, but I've reached the limit of what I can "
    "assist with in this conversation. For anything further, a real USPS "
    "representative will be able to help you much better than I can.\n\n"
    "Call: 1-800-275-8777 (Mon-Fri 8 AM-8:30 PM ET, Sat 8 AM-6 PM ET)\n"
    "Chat or email: https://www.usps.com/help/contact-us.htm"
)

# ---------------------------------------------------------------------------
# System prompt  —  V2
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

SUMMARIZATION — CRITICAL:
Your answer must be strictly under 100 words. Count carefully. Be direct \
and concise. Summarize the key information from the retrieved content — \
do not quote full articles or list every detail. If a source URL is \
available, add it on a new line as: "For more details: <url>"

CONVERSATION MEMORY:
You will receive the conversation history. Use it to give contextually \
relevant answers. If the customer refers to something mentioned earlier \
(e.g. "what about that?", "and the other one?"), use the prior messages \
to understand what they mean.

ESCALATION — call escalate_to_human if:
- No relevant content was found above the similarity threshold
- The question involves complaints, payments, account issues, or disputes
- You cannot confidently answer from the retrieved content

TONE:
Calm, concise, and plain language. Users may be frustrated — be \
empathetic and direct. Keep answers brief; avoid jargon. No markdown, \
no bullet points, no bold text. Plain sentences only.

SCOPE:
If the question is not related to USPS services, politely say it is \
outside your scope and offer to connect them with a USPS representative \
via escalate_to_human.\
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
    return json.dumps({
        "escalated": True,
        "reason": reason,
        "contact_options": {
            "phone":     "1-800-275-8777 (1-800-ASK-USPS), Mon-Fri 8 AM-8:30 PM ET, Sat 8 AM-6 PM ET",
            "live_chat": "https://www.usps.com/help/contact-us.htm",
            "help_page": "https://www.usps.com/help/welcome.htm",
        },
        "instruction": (
            "Tell the customer warmly that you are connecting them with a real "
            "USPS representative, and provide all three contact options above. "
            "Keep it empathetic — they may be frustrated."
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
# Pre-flight classifier
# ---------------------------------------------------------------------------
CLASSIFIER_PROMPT = """\
You are a routing classifier for a USPS customer service chatbot.

Your job: decide whether the customer's question is clear enough to search \
a knowledge base, or whether ONE clarifying question is needed first.

RULES — read carefully:

1. NEVER ask for personal data: tracking numbers, addresses, account numbers, \
   order IDs, names, or any identifying information. This is a demo without \
   access to USPS systems — we cannot look up individual shipments.

2. NEVER ask a clarifying question when the question mentions a specific USPS \
   service by name — Priority Mail, First-Class Mail, Informed Delivery, \
   Media Mail, USPS Ground Advantage, PO Box, Certified Mail, etc. \
   These are specific enough to search directly.

3. NEVER ask a clarifying question for these topics — answer generically:
   - Tracking a package or checking delivery status
   - Missing, lost, or delayed mail or packages
   - Any question that is a natural follow-up in the conversation history

4. ASK a clarifying question only when the TOPIC itself is so vague that \
   different interpretations would lead to completely different answers. \
   Good examples: "How long does it take?" (which service? domestic or \
   international?), "Can I change my delivery?" (change what — address, \
   time, hold, redirect?), "How do I ship something?" (domestic vs \
   international changes the answer entirely).

5. ONE QUESTION ONLY — critical: you must choose the single most important \
   thing to clarify. Write one short, direct question. Do not list options, \
   do not ask multiple questions, do not use "or" to embed two questions. \
   If you catch yourself writing more than one sentence or more than one \
   question mark, stop and rewrite as a single question.

EXAMPLE OF CORRECT OUTPUT for an ambiguous question:
Question: "How long does it take?"
Output: {{"needs_clarification": true, "clarifying_question": "Are you asking about a specific mail service, like Priority Mail or First-Class?"}}

EXAMPLE OF CORRECT OUTPUT for a clear question:
Question: "How do I track a package?"
Output: {{"needs_clarification": false, "clarifying_question": null}}

CONVERSATION HISTORY (last few messages, may be empty):
{history_str}

CURRENT QUESTION: {question}

Respond ONLY with valid JSON — no preamble, no markdown:
{{"needs_clarification": true or false, "clarifying_question": "..." or null}}\
"""


def classify_question(
    question: str,
    client: anthropic.Anthropic,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Pre-flight classifier: determines whether the question needs a clarifying
    question before retrieval, or can proceed directly to the agent loop.

    Returns:
        {"needs_clarification": bool, "clarifying_question": str | None}
    """
    history = conversation_history or []
    history_str = (
        "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-4:])
        if history else "(none)"
    )

    prompt = CLASSIFIER_PROMPT.format(
        history_str=history_str,
        question=question,
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=120,
            temperature=0.0,   # deterministic — this is classification, not generation
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        # Sanitise: ensure expected keys exist
        return {
            "needs_clarification": bool(result.get("needs_clarification", False)),
            "clarifying_question": result.get("clarifying_question") or None,
        }
    except (json.JSONDecodeError, IndexError, KeyError):
        # If classifier fails for any reason, default to proceeding with retrieval
        return {"needs_clarification": False, "clarifying_question": None}


# ---------------------------------------------------------------------------
# Shared early-exit type for pre-flight + turn-limit returns
# ---------------------------------------------------------------------------
# A return value with this key set means we should skip retrieval entirely.
_EARLY_EXIT = "_early_exit"


# ---------------------------------------------------------------------------
# run_agent_tools  —  pre-flight + retrieval loop (no final generation)
# ---------------------------------------------------------------------------
def run_agent_tools(
    question: str,
    client: anthropic.Anthropic,
    supabase: Client,
    vo: voyageai.Client,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    turn_number: int = 1,
) -> Dict[str, Any]:
    """
    Runs the pre-flight classifier, turn-limit check, and tool-calling loop.
    Does NOT make the final generation call — that is left to the caller so
    it can be done with either create() (CLI) or stream() (HTTP endpoint).

    Returns one of two shapes:

    Early-exit (clarification needed or turn limit reached):
        {"_early_exit": True, "answer": str, "escalated": bool,
         "needs_clarification": bool, "source_title": None,
         "source_url": None, "similarity_score": None}

    Ready for final generation:
        {"_early_exit": False, "messages": [...], "meta": {...}}
        where meta has source_title, source_url, similarity_score, escalated.
    """

    # ── Pre-flight: classify before doing anything else ──
    classification = classify_question(question, client, conversation_history)
    if classification["needs_clarification"] and classification["clarifying_question"]:
        return {
            _EARLY_EXIT:           True,
            "answer":              classification["clarifying_question"],
            "source_title":        None,
            "source_url":          None,
            "similarity_score":    None,
            "escalated":           False,
            "needs_clarification": True,
        }

    # ── Turn limit ──
    if turn_number > MAX_TURNS:
        return {
            _EARLY_EXIT:           True,
            "answer":              TURN_LIMIT_MESSAGE,
            "source_title":        None,
            "source_url":          None,
            "similarity_score":    None,
            "escalated":           True,
            "needs_clarification": False,
        }

    # ── Build message list: history + current question ──
    history: List[Dict[str, Any]] = conversation_history or []
    messages: List[Dict[str, Any]] = history + [{"role": "user", "content": question}]

    meta: Dict[str, Any] = {
        "source_title":     None,
        "source_url":       None,
        "similarity_score": None,
        "escalated":        False,
    }

    # ── First call: force search_usps_knowledge ──
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        tool_choice={"type": "tool", "name": "search_usps_knowledge"},
        messages=messages,
    )

    # ── Tool-calling loop ──
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

    # Tool loop is done — messages is ready for the final generation call
    return {_EARLY_EXIT: False, "messages": messages, "meta": meta}


# ---------------------------------------------------------------------------
# run_agent  —  non-streaming (CLI / testing)
# ---------------------------------------------------------------------------
def run_agent(
    question: str,
    client: anthropic.Anthropic,
    supabase: Client,
    vo: voyageai.Client,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    turn_number: int = 1,
) -> Dict[str, Any]:
    """
    Full non-streaming agent call. Used by the CLI and evals.

    Returns a dict with keys:
        answer, source_title, source_url, similarity_score,
        escalated, needs_clarification
    """
    tools_result = run_agent_tools(
        question, client, supabase, vo, conversation_history, turn_number
    )

    # Early-exit path (clarification or turn limit)
    if tools_result[_EARLY_EXIT]:
        return {k: v for k, v in tools_result.items() if k != _EARLY_EXIT}

    # Final generation call (non-streaming)
    messages = tools_result["messages"]
    meta     = tools_result["meta"]

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
    return {"answer": answer, "needs_clarification": False, **meta}


# ---------------------------------------------------------------------------
# run_agent_stream  —  streaming generator (used by app.py SSE endpoint)
# ---------------------------------------------------------------------------
from typing import Generator


def run_agent_stream(
    question: str,
    client: anthropic.Anthropic,
    supabase: Client,
    vo: voyageai.Client,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    turn_number: int = 1,
) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming variant of run_agent. Yields dicts that app.py serialises to SSE.

    Yields:
        {"type": "token",  "text": "<chunk>"}        — one per streamed token
        {"type": "done",   "source_title": ...,
                           "source_url": ...,
                           "similarity_score": ...,
                           "escalated": bool,
                           "needs_clarification": bool}  — final metadata event

    The caller (app.py) converts each yielded dict into an SSE line:
        data: <json>\n\n
    """
    tools_result = run_agent_tools(
        question, client, supabase, vo, conversation_history, turn_number
    )

    # Early-exit: yield the full answer as a single token, then done
    if tools_result[_EARLY_EXIT]:
        payload = {k: v for k, v in tools_result.items() if k != _EARLY_EXIT}
        yield {"type": "token", "text": payload["answer"]}
        yield {
            "type":                "done",
            "source_title":        payload.get("source_title"),
            "source_url":          payload.get("source_url"),
            "similarity_score":    payload.get("similarity_score"),
            "escalated":           payload.get("escalated", False),
            "needs_clarification": payload.get("needs_clarification", False),
        }
        return

    # Normal path: stream the final generation
    messages = tools_result["messages"]
    meta     = tools_result["meta"]

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=messages,
    ) as stream:
        for text_chunk in stream.text_stream:
            yield {"type": "token", "text": text_chunk}

    yield {
        "type":                "done",
        "source_title":        meta.get("source_title"),
        "source_url":          meta.get("source_url"),
        "similarity_score":    meta.get("similarity_score"),
        "escalated":           meta.get("escalated", False),
        "needs_clarification": False,
    }


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
    print("  USPS Customer Service Agent  —  V2")
    print(f"  Model: {CLAUDE_MODEL}  |  Threshold: {MATCH_THRESHOLD}  |  Max turns: {MAX_TURNS}")
    print("  Type 'quit' to exit.")
    print("=" * 60)

    # CLI maintains its own history for manual testing
    cli_history: List[Dict[str, Any]] = []
    turn = 1

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

        print(f"\n[Turn {turn}]")
        print("Agent: ", end="", flush=True)

        result = run_agent(
            question=question,
            client=claude,
            supabase=supabase,
            vo=vo,
            conversation_history=cli_history[-6:],  # last 3 exchanges = 6 messages
            turn_number=turn,
        )

        print(result["answer"])

        # Advance history and turn counter only after a reply is received
        cli_history.append({"role": "user",      "content": question})
        cli_history.append({"role": "assistant",  "content": result["answer"]})
        turn += 1


if __name__ == "__main__":
    main()
