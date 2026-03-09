#!/usr/bin/env python3
# Production threshold: 0.5 - chosen based on escalation test results showing 2/2 PASS only at 0.5
"""
eval_llm_judge.py

For each threshold (0.3, 0.4, 0.5) and each of the 10 golden questions:
  1. Reads the top retrieved article title from eval_results.json
     (using the winning model: multi-qa-MiniLM-L6-cos-v1)
  2. Looks up the article content in usps_cleaned.json and takes
     the first 500-token chunk (matching embed_usps.py chunking logic)
  3. Calls Claude to generate an answer using ONLY that chunk as context
  4. Calls Claude again as an LLM judge to score:
       - Faithfulness (1-5), Answer Relevance (1-5), Overall (1-5)

Also evaluates 2 escalation questions (expected: ESCALATE):
  - If retrieval returned NO results above ESCALATION_THRESHOLD: auto-PASS
  - If results were returned: generates an answer and judges whether the
    bot correctly declined to answer / escalated

Golden judge results are loaded from the existing eval_judge_results.json.
Only the 2 escalation questions are newly evaluated.
Saves combined results back to eval_judge_results.json.

API calls are cached by (question, retrieved_title) so identical top results
across thresholds do not trigger duplicate calls.

Reads ANTHROPIC_API_KEY from .env
"""

import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL                = "claude-sonnet-4-0"   # claude-sonnet-4-20250514
RETRIEVAL_MODEL      = "multiqa"
CHUNK_TOKENS         = 500
EVAL_INPUT           = "eval_results.json"
CLEANED_INPUT        = "usps_cleaned.json"
JUDGE_INPUT          = "eval_judge_results.json"
OUTPUT_FILE          = "eval_judge_results.json"
ESCALATION_THRESHOLD = 0.5  # production threshold

ESCALATION_QUESTIONS = [
    "What is the best smartphone to buy?",
    "How do I fix my internet connection?",
]

GENERATOR_SYSTEM = (
    "You are a helpful USPS customer service assistant. "
    "Answer the user's question using ONLY the information provided in the context. "
    "If the context does not contain enough information to fully answer, say so clearly. "
    "Be concise and direct."
)

JUDGE_SYSTEM = """You are an expert evaluator of RAG (Retrieval-Augmented Generation) systems.

You will be given a question, the retrieved context used to answer it, and the generated answer.
Score the answer on three dimensions and provide a brief reason for each.

Return ONLY valid JSON with this exact structure — no markdown, no explanation outside the JSON:
{
  "faithfulness": {
    "score": <integer 1-5>,
    "reason": "<one sentence>"
  },
  "answer_relevance": {
    "score": <integer 1-5>,
    "reason": "<one sentence>"
  },
  "overall": {
    "score": <integer 1-5>,
    "reason": "<one sentence>"
  }
}

Scoring rubric:
  Faithfulness (1-5): 5 = fully grounded, zero hallucination; 1 = largely fabricated
  Answer Relevance (1-5): 5 = directly answers the question; 1 = off-topic
  Overall (1-5): 5 = excellent; 1 = poor"""

ESCALATION_JUDGE_SYSTEM = """You are evaluating whether a USPS chatbot correctly handles out-of-scope questions.

The chatbot should ONLY answer questions about USPS mail and shipping services.
For questions about unrelated topics (smartphones, internet, etc.), it should politely
decline and suggest the user seek help elsewhere.

You will be given the question and the chatbot's response.

Return ONLY valid JSON — no markdown, no text outside the JSON:
{
  "escalated_correctly": <true or false>,
  "confidence": <integer 1-5>,
  "reason": "<one sentence explaining the verdict>"
}

Scoring for confidence:
  5 = bot clearly and politely declined / redirected
  3 = bot partially declined but gave some off-topic content
  1 = bot fully attempted to answer the out-of-scope question"""

SEP  = "─" * 72
SEP2 = "═" * 72

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def first_chunk(content: str, max_tokens: int = CHUNK_TOKENS) -> str:
    return " ".join(content.split()[:max_tokens])


def build_article_index(cleaned_path: str) -> Dict[str, str]:
    with open(cleaned_path) as f:
        data = json.load(f)
    return {p["title"].lower().strip(): p["content"] for p in data["pages"]}


def find_content(index: Dict[str, str], title: str) -> Optional[str]:
    key = title.lower().strip()
    if key in index:
        return index[key]
    for stored_title, content in index.items():
        if key in stored_title or stored_title in key:
            return content
    return None


def parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"    [WARN] Could not parse JSON: {e}")
        return {}


def generate_answer(client: anthropic.Anthropic, question: str, context: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=GENERATOR_SYSTEM,
        messages=[{"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}]
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def judge_answer(
    client: anthropic.Anthropic, question: str, context: str, answer: str
) -> Dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"Retrieved Context:\n{context}\n\n"
                f"Generated Answer:\n{answer}"
            )
        }]
    )
    raw = next((b.text for b in response.content if b.type == "text"), "{}")
    result = parse_json_response(raw)
    if not result:
        return {
            "faithfulness":     {"score": 0, "reason": "parse error"},
            "answer_relevance": {"score": 0, "reason": "parse error"},
            "overall":          {"score": 0, "reason": "parse error"},
        }
    return result


def judge_escalation(
    client: anthropic.Anthropic, question: str, answer: str
) -> Dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=ESCALATION_JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Question: {question}\n\nChatbot Response:\n{answer}"
        }]
    )
    raw = next((b.text for b in response.content if b.type == "text"), "{}")
    result = parse_json_response(raw)
    if not result:
        return {"escalated_correctly": False, "confidence": 0, "reason": "parse error"}
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY must be set in .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Load retrieval results (must include escalation data from eval_retrieval.py)
    print(f"Loading {EVAL_INPUT}...")
    with open(EVAL_INPUT) as f:
        eval_data = json.load(f)
    thresholds_data  = eval_data.get("thresholds", {})
    thresholds       = sorted(float(k) for k in thresholds_data)
    print(f"  Found thresholds: {thresholds}\n")

    # Load existing golden judge results (avoid re-running the 10 golden questions)
    print(f"Loading existing golden judge results from {JUDGE_INPUT}...")
    try:
        with open(JUDGE_INPUT) as f:
            existing_judge = json.load(f)
        existing_judge_thresholds = existing_judge.get("thresholds", {})
        print(f"  Loaded judge results for thresholds: {list(existing_judge_thresholds.keys())}\n")
    except FileNotFoundError:
        print("  WARNING: eval_judge_results.json not found — golden judge scores will show as n/a.\n")
        existing_judge_thresholds = {}

    print(f"Loading {CLEANED_INPUT}...")
    article_index = build_article_index(CLEANED_INPUT)
    print(f"  {len(article_index)} articles indexed.\n")

    # Cache: (question, top_title) → (answer, scores)
    answer_cache: Dict[Tuple[str, str], Tuple[str, Dict]] = {}
    api_calls_saved = 0

    # Escalation results keyed by threshold
    esc_judge_by_threshold: Dict[str, List[dict]] = {}

    print(SEP2)
    print(f"{'ESCALATION JUDGE EVALUATION  (model: ' + MODEL + ')':^72}")
    print(SEP2)

    for threshold in thresholds:
        t_key     = str(threshold)
        esc_list  = thresholds_data.get(t_key, {}).get("escalation", [])

        if not esc_list:
            print(f"\n[SKIP] No escalation data in eval_results.json for threshold {threshold}.")
            print("       Run eval_retrieval.py first to generate escalation results.\n")
            continue

        print(f"\n{SEP2}")
        print(f"  THRESHOLD: {threshold}")
        print(SEP2)

        threshold_esc_results: List[dict] = []

        for i, esc_data in enumerate(esc_list, 1):
            question    = esc_data["question"]
            retrieval_passed = esc_data["passed"]  # True = no results above ESCALATION_THRESHOLD
            model_res   = esc_data.get("models", {}).get(RETRIEVAL_MODEL, {})
            results_list = model_res.get("results", [])
            max_sim      = model_res.get("max_similarity", 0.0)

            print(f"\n  ESC{i}: {question}")
            print(f"  Retrieval PASS: {retrieval_passed}  (max sim={max_sim:.3f})")
            print(SEP)

            if retrieval_passed:
                # No results above threshold — bot would correctly not attempt an answer
                print("  [AUTO-PASS] No results above escalation threshold — bot would decline.")
                verdict = {
                    "escalated_correctly": True,
                    "confidence":          5,
                    "reason":              "No results returned above threshold; bot would correctly decline.",
                    "auto_pass":           True,
                }
                threshold_esc_results.append({
                    "question":          question,
                    "expected":          "ESCALATE",
                    "retrieval_passed":  True,
                    "max_similarity":    max_sim,
                    "answer":            None,
                    "escalation_verdict": verdict,
                    "cache_hit":         False,
                })
            else:
                # Results were returned — generate an answer and judge if it escalates correctly
                top_title = results_list[0].get("title", "") if results_list else ""
                article_content = find_content(article_index, top_title) if top_title else None

                if not article_content:
                    # No article content to use — use empty context
                    context = "(No relevant USPS content found)"
                else:
                    context = first_chunk(article_content, CHUNK_TOKENS)

                cache_key = (question, top_title)
                cache_hit = cache_key in answer_cache

                print(f"  Top result : {top_title or '—'} (sim={max_sim:.3f})"
                      + ("  [cached]" if cache_hit else ""))

                if cache_hit:
                    answer, _ = answer_cache[cache_key]
                    api_calls_saved += 1
                else:
                    try:
                        answer = generate_answer(client, question, context)
                    except Exception as e:
                        print(f"  [ERROR] Generation failed: {e}")
                        answer = ""
                    time.sleep(0.5)

                print(f"  Answer     : {answer[:200]}{'...' if len(answer) > 200 else ''}")

                # Judge whether the bot escalated correctly
                try:
                    verdict = judge_escalation(client, question, answer)
                except Exception as e:
                    print(f"  [ERROR] Escalation judge failed: {e}")
                    verdict = {"escalated_correctly": False, "confidence": 0, "reason": str(e)}

                if not cache_hit:
                    answer_cache[cache_key] = (answer, verdict)
                    time.sleep(0.5)
                else:
                    api_calls_saved += 1

                correctly = verdict.get("escalated_correctly", False)
                conf      = verdict.get("confidence", 0)
                reason    = verdict.get("reason", "")
                label     = "PASS ✓" if correctly else "FAIL ✗"
                print(f"  Verdict    : {label}  (confidence={conf}/5) — {reason}")

                threshold_esc_results.append({
                    "question":           question,
                    "expected":           "ESCALATE",
                    "retrieval_passed":   False,
                    "max_similarity":     max_sim,
                    "context_used":       context,
                    "answer":             answer,
                    "escalation_verdict": verdict,
                    "cache_hit":          cache_hit,
                })

        passes = sum(1 for r in threshold_esc_results
                     if r["escalation_verdict"].get("escalated_correctly", False))
        print(f"\n  Escalation pass rate @ {threshold}: {passes}/{len(threshold_esc_results)}")
        esc_judge_by_threshold[t_key] = threshold_esc_results

    # ---------------------------------------------------------------------------
    # Combined comparison scorecard
    # ---------------------------------------------------------------------------
    print(f"\n\n{SEP2}")
    print(f"{'COMPARISON SCORECARD — ALL THRESHOLDS':^72}")
    print(SEP2)

    print(f"\n  ── Golden Questions (10) — Retrieval + LLM Judge (multi-qa) ──")
    print(f"  {'Threshold':>9}  {'HR@5':>6}  {'MRR':>6}  {'Faithful':>9}  {'Relevance':>10}  {'Overall':>8}")
    print(f"  {'-'*9}  {'-'*6}  {'-'*6}  {'-'*9}  {'-'*10}  {'-'*8}")

    for threshold in thresholds:
        t_key  = str(threshold)
        # Retrieval metrics from eval_results.json
        ret    = thresholds_data.get(t_key, {}).get("summary", {}).get(RETRIEVAL_MODEL, {})
        hr     = f"{ret['hit_rate_at_5']:.1%}" if "hit_rate_at_5" in ret else "  n/a"
        mrr    = f"{ret['mrr']:.3f}"           if "mrr" in ret           else "  n/a"
        # LLM judge metrics from existing eval_judge_results.json
        jt     = existing_judge_thresholds.get(t_key, {})
        faith  = f"{jt['avg_faithfulness']:.2f}"     if "avg_faithfulness"     in jt else "  n/a"
        relev  = f"{jt['avg_answer_relevance']:.2f}" if "avg_answer_relevance" in jt else "  n/a"
        ovall  = f"{jt['avg_overall']:.2f}"          if "avg_overall"          in jt else "  n/a"
        print(f"  {threshold:>9.1f}  {hr:>6}  {mrr:>6}  {faith:>9}  {relev:>10}  {ovall:>8}")

    print(f"\n  ── Escalation Tests (2 questions, PASS = correctly declined) ──")
    print(f"  {'Threshold':>9}  {'Retrieval':>10}  {'LLM Escalation':>15}")
    print(f"  {'-'*9}  {'-'*10}  {'-'*15}")

    for threshold in thresholds:
        t_key    = str(threshold)
        esc_list = esc_judge_by_threshold.get(t_key, [])
        if not esc_list:
            print(f"  {threshold:>9.1f}  {'n/a':>10}  {'n/a':>15}")
            continue
        # Retrieval pass = no results above escalation threshold
        ret_esc  = thresholds_data.get(t_key, {}).get("escalation", [])
        ret_pass = sum(1 for r in ret_esc if r.get("passed", False))
        # LLM judge pass = correctly escalated
        llm_pass = sum(1 for r in esc_list
                       if r["escalation_verdict"].get("escalated_correctly", False))
        n = len(esc_list)
        print(f"  {threshold:>9.1f}  {ret_pass}/{n} {'PASS' if ret_pass == n else 'FAIL':>6}  "
              f"  {llm_pass}/{n} {'PASS' if llm_pass == n else 'FAIL':>6}")

    if api_calls_saved:
        print(f"\n  ({api_calls_saved} API calls saved via cache)")
    print()

    # ---------------------------------------------------------------------------
    # Save — merge escalation judge results into existing data
    # ---------------------------------------------------------------------------
    for threshold in thresholds:
        t_key = str(threshold)
        if t_key not in existing_judge_thresholds:
            existing_judge_thresholds[t_key] = {}
        t_data = existing_judge_thresholds[t_key]

        esc_results = esc_judge_by_threshold.get(t_key, [])
        passes      = sum(1 for r in esc_results
                          if r["escalation_verdict"].get("escalated_correctly", False))
        t_data["escalation"] = {
            "pass_rate":  passes / len(esc_results) if esc_results else None,
            "n":          len(esc_results),
            "results":    esc_results,
        }

    output = {
        "evaluated_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator_model": MODEL,
        "judge_model":     MODEL,
        "retrieval_model": "multi-qa-MiniLM-L6-cos-v1",
        "chunk_tokens":    CHUNK_TOKENS,
        "thresholds":      existing_judge_thresholds,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Full results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")
