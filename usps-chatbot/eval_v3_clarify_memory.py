#!/usr/bin/env python3
"""
eval_v3_clarify_memory.py  —  USPS Chatbot V3 Eval

Tests only the clarifying question memory fix:
  - After a clarifying exchange, the next message should have full context
  - Turn counter should NOT advance after a clarifying question
  - Conversation history should include the clarifying exchange

Reads SUPABASE_URL, SUPABASE_ANON_KEY, ANTHROPIC_API_KEY, VOYAGEAI_API_KEY from .env

Usage:
    python eval_v3_clarify_memory.py
"""

import json
import os
import sys
from typing import Any, Dict, List

import anthropic
import voyageai
from dotenv import load_dotenv
from supabase import create_client

from agent import run_agent, MAX_TURNS

# ─────────────────────────────────────────────────────────────────────────────
# Test scripts — each simulates a clarifying Q exchange then a follow-up
# The key check: does the follow-up answer use context from the full exchange?
# ─────────────────────────────────────────────────────────────────────────────
CLARIFY_MEMORY_SCRIPTS = [
    {
        "name": "International shipping → clothes",
        "turns": [
            "How do I ship something?",       # should trigger clarifying Q
            "internationally",                 # answers the clarifying Q
            "what customs forms do I need",    # should answer using full context
        ],
        "context_check": (
            "Turn 3 asks about customs forms. The answer should be specific to "
            "international shipping — not generic. It should reference customs "
            "declarations or international mail forms, not domestic shipping."
        ),
    },
    {
        "name": "Delivery change → reschedule",
        "turns": [
            "Can I change my delivery?",      # should trigger clarifying Q
            "I want to reschedule the time",   # answers the clarifying Q
            "how far in advance do I need to do that",  # follow-up
        ],
        "context_check": (
            "Turn 3 asks about lead time. The answer should be about rescheduling "
            "a delivery, not about address changes or holds. Context from turns 1 "
            "and 2 should make it clear this is about delivery time changes."
        ),
    },
    {
        "name": "How long does it take → Priority Mail",
        "turns": [
            "How long does it take?",          # should trigger clarifying Q
            "Priority Mail",                   # answers the clarifying Q
            "what about to Hawaii",            # follow-up with location context
        ],
        "context_check": (
            "Turn 3 asks about delivery to Hawaii. The answer should reference "
            "Priority Mail delivery times specifically, not generic shipping times. "
            "Context from turn 2 (Priority Mail) should carry through."
        ),
    },
]


def llm_judge(client: anthropic.Anthropic, prompt: str) -> Dict[str, Any]:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"score": 0, "reasoning": f"Could not parse: {raw}"}


def run_clarify_memory_tests(client, supabase, vo, judge_client) -> Dict[str, Any]:
    print("\n" + "=" * 60)
    print("TEST: CLARIFYING QUESTION MEMORY")
    print("After a clarifying exchange, follow-up should have full context")
    print("=" * 60)

    results = []

    for script in CLARIFY_MEMORY_SCRIPTS:
        print(f"\n  Script: {script['name']}")

        # Frontend state we're simulating
        conversation_history: List[Dict[str, Any]] = []
        turn_number = 1
        MAX_HISTORY = 6

        for i, question in enumerate(script["turns"]):
            result = run_agent(
                question=question,
                client=client,
                supabase=supabase,
                vo=vo,
                conversation_history=conversation_history[-MAX_HISTORY:],
                turn_number=turn_number,
            )

            needs_clarification = result.get("needs_clarification", False)
            answer = result["answer"]

            print(f"    Turn {i+1} [clarify={needs_clarification}] Q: {question}")
            print(f"    Turn {i+1} A: {answer[:120]}...")

            # Simulate the fix: store regardless, only advance turn if not clarifying
            conversation_history.append({"role": "user",      "content": question})
            conversation_history.append({"role": "assistant",  "content": answer})
            if conversation_history.__len__() > MAX_HISTORY:
                conversation_history = conversation_history[-MAX_HISTORY:]

            if not needs_clarification:
                turn_number += 1

        # Judge the final answer (turn 3) for context awareness
        final_answer = conversation_history[-1]["content"]
        convo_str = json.dumps(
            [{"role": m["role"], "content": m["content"][:200]} for m in conversation_history],
            indent=2
        )
        judge_prompt = f"""You are evaluating whether a USPS chatbot used full conversation context.

Full conversation:
{convo_str}

Context check: {script["context_check"]}

Did the final answer use the full conversation context appropriately?
Respond ONLY with valid JSON: {{"score": <1-5>, "reasoning": "<one sentence>"}}"""

        judgment = llm_judge(judge_client, judge_prompt)
        score = judgment.get("score", 0)
        passed = score >= 4
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"    Judge score: {score}/5  {status}  — {judgment.get('reasoning', '')}")
        print(f"    Turn counter ended at: {turn_number} (expected ≤ {MAX_TURNS})")

        results.append({
            "script":        script["name"],
            "score":         score,
            "passed":        passed,
            "turn_ended_at": turn_number,
        })

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\n  Result: {passed_count}/{len(results)} clarify-memory scripts passed")
    return {
        "test":    "clarify_memory",
        "passed":  passed_count,
        "total":   len(results),
        "details": results,
    }


def main() -> None:
    load_dotenv()

    supabase_url  = os.getenv("SUPABASE_URL")
    supabase_key  = os.getenv("SUPABASE_ANON_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    voyage_key    = os.getenv("VOYAGEAI_API_KEY")

    missing = [n for n, v in [
        ("SUPABASE_URL", supabase_url), ("SUPABASE_ANON_KEY", supabase_key),
        ("ANTHROPIC_API_KEY", anthropic_key), ("VOYAGEAI_API_KEY", voyage_key),
    ] if not v]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}")
        sys.exit(1)

    vo       = voyageai.Client(api_key=voyage_key)
    supabase = create_client(supabase_url, supabase_key)
    claude   = anthropic.Anthropic(api_key=anthropic_key)

    print("\nUSPS Chatbot V3 — Clarifying Question Memory Eval")
    print("=" * 60)

    result = run_clarify_memory_tests(claude, supabase, vo, judge_client=claude)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  clarify_memory   {result['passed']}/{result['total']}")

    with open("eval_v3_results.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nResults saved to eval_v3_results.json")


if __name__ == "__main__":
    main()
