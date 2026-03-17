#!/usr/bin/env python3
"""
eval_v2_agent.py  —  USPS Chatbot V2 Agent Evals

Covers:
  1. Word count compliance  — all answers ≤ 100 words
  2. Turn counter / escalation — turn 4 always returns escalation
  3. Memory / context relevance — follow-up Qs answered using prior context
  4. Clarifying question behavior — fires on ambiguous Qs, not on clear Qs,
     and never more than once per turn

Reads SUPABASE_URL, SUPABASE_ANON_KEY, ANTHROPIC_API_KEY, VOYAGEAI_API_KEY from .env

Usage:
    python eval_v2_agent.py
"""

import json
import os
import sys
from typing import Any, Dict, List

import anthropic
import voyageai
from dotenv import load_dotenv
from supabase import create_client

from agent import run_agent, TURN_LIMIT_MESSAGE, MAX_TURNS

# ─────────────────────────────────────────────────────────────────────────────
# 1. WORD COUNT TEST SET  (reuse the 20 golden questions from V1)
# ─────────────────────────────────────────────────────────────────────────────
WORD_COUNT_QUESTIONS = [
    "How do I track my package?",
    "What is USPS Informed Delivery?",
    "How do I hold my mail while on vacation?",
    "How do I submit a missing mail search?",
    "What are USPS Priority Mail delivery times?",
    "How do I file a claim for a damaged package?",
    "Can I redirect a package to a different address?",
    "What is the cost to mail a letter domestically?",
    "How do I schedule a package pickup?",
    "What is the difference between First-Class and Priority Mail?",
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. TURN COUNTER TEST
#    After MAX_TURNS exchanges, turn MAX_TURNS+1 must return escalation.
# ─────────────────────────────────────────────────────────────────────────────
TURN_COUNTER_CONVERSATION = [
    "How do I track my package?",
    "How do I hold my mail?",
    "What is Priority Mail?",
    "How do I file a damage claim?",   # turn 4 — should escalate
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. MEMORY / CONTEXT RELEVANCE TEST
#    Turn 2 or 3 only makes sense with context from earlier turns.
#    LLM judge scores whether context was used.
# ─────────────────────────────────────────────────────────────────────────────
MEMORY_SCRIPTS = [
    {
        "name": "Package tracking follow-up",
        "turns": [
            "How do I track my package?",
            "What if it says delivered but I never received it?",
        ],
        "context_check": "The answer to turn 2 should reference the delivery scenario, not restart from scratch.",
    },
    {
        "name": "Mail hold follow-up",
        "turns": [
            "How do I hold my mail while on vacation?",
            "How far in advance do I need to set that up?",
        ],
        "context_check": "Turn 2 'that' refers to the mail hold. Answer should mention lead time for mail holds.",
    },
    {
        "name": "Priority Mail follow-up",
        "turns": [
            "What is Priority Mail?",
            "How does it compare to First-Class?",
        ],
        "context_check": "Turn 2 should compare Priority Mail (mentioned in turn 1) to First-Class Mail.",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 4. CLARIFYING QUESTION TEST
#    5 ambiguous (should ask), 5 specific (should NOT ask)
# ─────────────────────────────────────────────────────────────────────────────
CLARIFYING_TESTS = [
    # (question, should_clarify, reason)
    ("Where is my package?",                          False, "Tracking questions answered generically — no clarification needed"),
    ("How do I ship something?",                      True,  "Too vague — domestic/international? size? service?"),
    ("What happened to my mail?",                     False, "Missing/delayed mail answered generically"),
    ("Can I change my delivery?",                     True,  "Ambiguous — could mean address, time, hold, redirect — different answers"),
    ("How long does it take?",                        True,  "No service or destination specified — answer differs significantly"),
    ("How do I track a USPS package with a tracking number?",  False, "Clear, specific question"),
    ("What is the price to mail a first-class letter?",        False, "Names a specific service — First-Class Mail"),
    ("How do I set up Informed Delivery?",                     False, "Specific named USPS feature"),
    ("How do I schedule a package pickup online?",             False, "Clear intent and channel"),
    ("How do I file a missing mail claim?",                    False, "Specific process question"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def word_count(text: str) -> int:
    return len(text.split())


def count_question_marks(text: str) -> int:
    """Count sentences ending in '?' as a proxy for questions asked."""
    return text.count("?")


def llm_judge(
    client: anthropic.Anthropic,
    prompt: str,
) -> Dict[str, Any]:
    """Ask Claude to judge a response. Returns {score, reasoning}."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    # Expect JSON from the prompt
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"score": 0, "reasoning": f"Could not parse judge response: {raw}"}


# ─────────────────────────────────────────────────────────────────────────────
# Test runners
# ─────────────────────────────────────────────────────────────────────────────
def run_word_count_tests(client, supabase, vo) -> Dict[str, Any]:
    print("\n" + "=" * 60)
    print("TEST 1: WORD COUNT COMPLIANCE (≤100 words)")
    print("=" * 60)

    results = []
    for q in WORD_COUNT_QUESTIONS:
        result = run_agent(q, client, supabase, vo, turn_number=1)
        wc = word_count(result["answer"])
        passed = wc <= 100
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  [{wc:3d} words]  {q[:60]}")
        results.append({"question": q, "word_count": wc, "passed": passed})

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\n  Result: {passed_count}/{len(results)} answers within 100 words")
    return {"test": "word_count", "passed": passed_count, "total": len(results), "details": results}


def run_turn_counter_test(client, supabase, vo) -> Dict[str, Any]:
    print("\n" + "=" * 60)
    print("TEST 2: TURN COUNTER — escalation on turn 4")
    print("=" * 60)

    history: List[Dict[str, Any]] = []
    escalated_correctly = False

    for i, question in enumerate(TURN_COUNTER_CONVERSATION):
        turn = i + 1
        result = run_agent(
            question=question,
            client=client,
            supabase=supabase,
            vo=vo,
            conversation_history=history[-6:],
            turn_number=turn,
        )
        is_escalation = result["escalated"]
        wc = word_count(result["answer"])
        print(f"  Turn {turn}: escalated={is_escalation}  [{wc} words]  Q: {question[:50]}")

        if turn == MAX_TURNS + 1:
            escalated_correctly = is_escalation
            print(f"  Answer preview: {result['answer'][:120]}...")

        # Only advance history on non-escalated turns
        if not is_escalation:
            history.append({"role": "user",      "content": question})
            history.append({"role": "assistant",  "content": result["answer"]})

    status = "✅ PASS" if escalated_correctly else "❌ FAIL"
    print(f"\n  Result: {status}  (turn {MAX_TURNS + 1} escalated = {escalated_correctly})")
    return {"test": "turn_counter", "passed": escalated_correctly}


def run_memory_tests(client, supabase, vo, judge_client) -> Dict[str, Any]:
    print("\n" + "=" * 60)
    print("TEST 3: MEMORY / CONTEXT RELEVANCE")
    print("=" * 60)

    results = []
    for script in MEMORY_SCRIPTS:
        print(f"\n  Script: {script['name']}")
        history: List[Dict[str, Any]] = []
        last_answer = ""

        for i, question in enumerate(script["turns"]):
            turn = i + 1
            result = run_agent(
                question=question,
                client=client,
                supabase=supabase,
                vo=vo,
                conversation_history=history[-6:],
                turn_number=turn,
            )
            print(f"    Turn {turn} Q: {question}")
            print(f"    Turn {turn} A: {result['answer'][:100]}...")
            last_answer = result["answer"]
            history.append({"role": "user",      "content": question})
            history.append({"role": "assistant",  "content": result["answer"]})

        # Judge: did the final answer use conversation context?
        judge_prompt = f"""You are evaluating whether a chatbot used conversation context correctly.

Conversation so far:
{json.dumps([{"role": m["role"], "content": m["content"][:200]} for m in history[:-2]], indent=2)}

Final question: {script["turns"][-1]}
Final answer: {last_answer}

Context check: {script["context_check"]}

Did the final answer appropriately use the conversation context to give a relevant, connected response?
Respond ONLY with valid JSON: {{"score": <1-5>, "reasoning": "<one sentence>"}}"""

        judgment = llm_judge(judge_client, judge_prompt)
        score = judgment.get("score", 0)
        passed = score >= 4
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"    Judge score: {score}/5  {status}  — {judgment.get('reasoning', '')}")
        results.append({"script": script["name"], "score": score, "passed": passed})

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\n  Result: {passed_count}/{len(results)} memory scripts passed (score ≥ 4)")
    return {"test": "memory", "passed": passed_count, "total": len(results), "details": results}


def run_clarifying_question_tests(client, supabase, vo, judge_client) -> Dict[str, Any]:
    print("\n" + "=" * 60)
    print("TEST 4: CLARIFYING QUESTION BEHAVIOR")
    print("=" * 60)

    results = []
    for question, should_clarify, reason in CLARIFYING_TESTS:
        result = run_agent(question, client, supabase, vo, turn_number=1)
        answer = result["answer"]
        q_marks = count_question_marks(answer)

        # Automated: never more than 1 question mark
        multi_question_fail = q_marks > 1

        # LLM judge: did it clarify when it should / not clarify when it shouldn't?
        judge_prompt = f"""A USPS chatbot received this question: "{question}"

The chatbot responded: "{answer}"

Expected behavior: {"Ask one clarifying question before answering" if should_clarify else "Answer directly without asking a clarifying question"}
Reason: {reason}

Did the chatbot behave correctly?
Respond ONLY with valid JSON: {{"score": <1-5>, "reasoning": "<one sentence>"}}"""

        judgment = llm_judge(judge_client, judge_prompt)
        score = judgment.get("score", 0)
        behavior_passed = score >= 4
        passed = behavior_passed and not multi_question_fail

        status = "✅ PASS" if passed else "❌ FAIL"
        clarify_label = "should clarify" if should_clarify else "should NOT clarify"
        print(f"  {status}  [{clarify_label}]  [?marks={q_marks}]  {question[:55]}")
        if not passed:
            print(f"         Judge: {score}/5 — {judgment.get('reasoning', '')}")

        results.append({
            "question": question,
            "should_clarify": should_clarify,
            "score": score,
            "multi_question_fail": multi_question_fail,
            "passed": passed,
        })

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\n  Result: {passed_count}/{len(results)} clarifying question tests passed")
    return {"test": "clarifying_question", "passed": passed_count, "total": len(results), "details": results}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
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

    print("\nUSPS Chatbot V2 — Agent Evals")
    print("=" * 60)

    all_results = []
    all_results.append(run_word_count_tests(claude, supabase, vo))
    all_results.append(run_turn_counter_test(claude, supabase, vo))
    all_results.append(run_memory_tests(claude, supabase, vo, judge_client=claude))
    all_results.append(run_clarifying_question_tests(claude, supabase, vo, judge_client=claude))

    # ── Summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in all_results:
        if "total" in r:
            print(f"  {r['test']:<30} {r['passed']}/{r['total']}")
        else:
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            print(f"  {r['test']:<30} {status}")

    # Save results
    with open("eval_v2_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nFull results saved to eval_v2_results.json")


if __name__ == "__main__":
    main()
