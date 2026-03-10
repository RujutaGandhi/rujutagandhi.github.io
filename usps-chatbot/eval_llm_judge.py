#!/usr/bin/env python3
"""
eval_llm_judge.py

For each threshold (0.3, 0.4, 0.5) and each of the 10 golden questions:
  1. Reads the top retrieved article title from eval_results.json
  2. Looks up the article content in usps_cleaned.json
  3. Calls Claude to generate an answer using ONLY that chunk as context
  4. Calls Claude again as LLM judge to score:
       - Faithfulness (1-5), Answer Relevance (1-5), Overall (1-5)

Also evaluates 2 escalation questions:
  - If retrieval returned NO results above threshold: auto-PASS
  - If results were returned: generates answer and judges whether bot escalated

API calls are cached by (question, retrieved_title) to avoid duplicate calls
across thresholds when the top result is the same.

Saves results to eval_judge_results.json.
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
MODEL                = "claude-sonnet-4-20250514"
CHUNK_TOKENS         = 500
EVAL_INPUT           = "eval_results.json"
CLEANED_INPUT        = "usps_cleaned.json"
OUTPUT_FILE          = "eval_judge_results.json"
ESCALATION_THRESHOLD = 0.5
THRESHOLDS           = [0.3, 0.4, 0.5]

SEP  = "─" * 72
SEP2 = "═" * 72

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
GENERATOR_SYSTEM = """\
You are a friendly USPS customer service assistant. Your goal is to help \
customers with their postal service questions quickly and clearly.

GROUNDEDNESS RULE — CRITICAL:
Answer ONLY using the retrieved context provided below. USPS policies, prices, \
and procedures change frequently — never rely on your training data. If the \
retrieved content does not contain the answer, do not guess.

ESCALATION — if the context does not contain a confident answer:
Politely tell the customer you cannot find the answer and provide these contact \
options: call 1-800-275-8777 (Mon–Fri 8 AM–8:30 PM ET, Sat 8 AM–6 PM ET), \
or visit usps.com/help/contact-us.htm

CITATIONS:
Every answer must include the source article title and URL if provided in the \
context. Format: "Source: <title> — <url>"

TONE:
Calm, concise, and plain language. Users may be frustrated — be empathetic and \
direct. Keep answers brief; avoid jargon.

SCOPE:
If the question is not related to USPS services, politely say it is outside \
your scope and provide the contact options above.

UNCERTAINTY:
If you are only partially confident based on the retrieved content, clearly \
state your uncertainty before providing the information.\
"""

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
}"""

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


def judge_answer(client: anthropic.Anthropic, question: str, context: str, answer: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": (
            f"Question: {question}\n\n"
            f"Retrieved Context:\n{context}\n\n"
            f"Generated Answer:\n{answer}"
        )}]
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


def judge_escalation(client: anthropic.Anthropic, question: str, answer: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=ESCALATION_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": f"Question: {question}\n\nChatbot Response:\n{answer}"}]
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

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY must be set in .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=anthropic_key)

    # Load retrieval results
    print(f"Loading {EVAL_INPUT}...")
    try:
        with open(EVAL_INPUT) as f:
            eval_data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {EVAL_INPUT} not found — run eval_retrieval.py first.")
        sys.exit(1)

    thresholds_data = eval_data.get("thresholds", {})

    # Load article content
    print(f"Loading {CLEANED_INPUT}...")
    article_index = build_article_index(CLEANED_INPUT)
    print(f"  {len(article_index)} articles indexed.\n")

    answer_cache: Dict[Tuple, Tuple] = {}
    api_calls_saved = 0
    judge_by_threshold: Dict[str, dict] = {}

    for threshold in THRESHOLDS:
        t_key    = str(threshold)
        t_data   = thresholds_data.get(t_key, {})
        questions = t_data.get("questions", [])
        esc_list  = t_data.get("escalation", [])

        print(SEP2)
        print(f"  THRESHOLD: {threshold}")
        print(SEP2)

        # --- Golden questions ---
        faith_scores  = []
        relev_scores  = []
        overall_scores = []
        question_judge_results = []

        for i, q_data in enumerate(questions, 1):
            question    = q_data["question"]
            top_results = q_data.get("top_results", [])
            top_title   = top_results[0]["title"] if top_results else ""

            content = find_content(article_index, top_title) if top_title else None
            context = first_chunk(content) if content else "(No relevant content found)"

            cache_key = (question, top_title)
            cache_hit = cache_key in answer_cache

            print(f"\n  Q{i}: {question}")
            print(f"  Top: {top_title[:50] or '—'}" + ("  [cached]" if cache_hit else ""))

            if cache_hit:
                answer, scores = answer_cache[cache_key]
                api_calls_saved += 2
            else:
                try:
                    answer = generate_answer(client, question, context)
                    time.sleep(0.5)
                    scores = judge_answer(client, question, context, answer)
                    time.sleep(0.5)
                    answer_cache[cache_key] = (answer, scores)
                except Exception as e:
                    print(f"  [ERROR] {e}")
                    answer = ""
                    scores = {
                        "faithfulness":     {"score": 0, "reason": str(e)},
                        "answer_relevance": {"score": 0, "reason": str(e)},
                        "overall":          {"score": 0, "reason": str(e)},
                    }

            f = scores.get("faithfulness",     {}).get("score", 0)
            r = scores.get("answer_relevance", {}).get("score", 0)
            o = scores.get("overall",          {}).get("score", 0)

            faith_scores.append(f)
            relev_scores.append(r)
            overall_scores.append(o)

            print(f"  Scores → Faithfulness: {f}/5  Relevance: {r}/5  Overall: {o}/5")
            question_judge_results.append({
                "question":      question,
                "top_title":     top_title,
                "answer":        answer,
                "scores":        scores,
                "cache_hit":     cache_hit,
            })

        avg_faith  = sum(faith_scores)  / len(faith_scores)  if faith_scores  else 0
        avg_relev  = sum(relev_scores)  / len(relev_scores)  if relev_scores  else 0
        avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0

        print(f"\n  Averages → Faithfulness: {avg_faith:.2f}  Relevance: {avg_relev:.2f}  Overall: {avg_overall:.2f}")

        # --- Escalation ---
        print(f"\n  ── Escalation Tests ──")
        esc_judge_results = []

        for j, esc_data in enumerate(esc_list, 1):
            question        = esc_data["question"]
            retrieval_passed = esc_data["passed"]
            max_sim         = esc_data.get("max_similarity", 0.0)

            print(f"\n  ESC{j}: {question}")
            print(f"  Retrieval PASS: {retrieval_passed}  (max_sim={max_sim:.3f})")

            if retrieval_passed:
                print("  [AUTO-PASS] No results above threshold — bot would correctly decline.")
                verdict = {
                    "escalated_correctly": True,
                    "confidence": 5,
                    "reason": "No results returned above threshold; bot would correctly decline.",
                    "auto_pass": True,
                }
                esc_judge_results.append({
                    "question": question, "retrieval_passed": True,
                    "max_similarity": max_sim, "answer": None,
                    "escalation_verdict": verdict,
                })
            else:
                top_results = esc_data.get("results", [])
                top_title   = top_results[0]["title"] if top_results else ""
                content     = find_content(article_index, top_title) if top_title else None
                context     = first_chunk(content) if content else "(No relevant content found)"

                cache_key = (question, top_title)
                cache_hit = cache_key in answer_cache

                if cache_hit:
                    answer, verdict = answer_cache[cache_key]
                    api_calls_saved += 2
                else:
                    try:
                        answer = generate_answer(client, question, context)
                        time.sleep(0.5)
                        verdict = judge_escalation(client, question, answer)
                        time.sleep(0.5)
                        answer_cache[cache_key] = (answer, verdict)
                    except Exception as e:
                        answer  = ""
                        verdict = {"escalated_correctly": False, "confidence": 0, "reason": str(e)}

                label = "PASS ✓" if verdict.get("escalated_correctly") else "FAIL ✗"
                print(f"  Verdict: {label}  (confidence={verdict.get('confidence', 0)}/5)")
                esc_judge_results.append({
                    "question": question, "retrieval_passed": False,
                    "max_similarity": max_sim, "answer": answer,
                    "escalation_verdict": verdict,
                })

        esc_passes = sum(1 for r in esc_judge_results
                         if r["escalation_verdict"].get("escalated_correctly", False))
        print(f"\n  Escalation pass rate: {esc_passes}/{len(esc_judge_results)}")

        judge_by_threshold[t_key] = {
            "avg_faithfulness":     avg_faith,
            "avg_answer_relevance": avg_relev,
            "avg_overall":          avg_overall,
            "questions":            question_judge_results,
            "escalation": {
                "pass_rate": esc_passes / len(esc_judge_results) if esc_judge_results else None,
                "n":         len(esc_judge_results),
                "results":   esc_judge_results,
            },
        }

    # --- Scorecard ---
    print(f"\n\n{SEP2}")
    print(f"{'SCORECARD — voyage-3-lite LLM Judge':^72}")
    print(SEP2)
    print(f"\n  {'Threshold':>10}  {'Faithful':>9}  {'Relevance':>10}  {'Overall':>8}  {'Escalation':>12}")
    print(f"  {'-'*10}  {'-'*9}  {'-'*10}  {'-'*8}  {'-'*12}")

    for threshold in THRESHOLDS:
        t  = judge_by_threshold[str(threshold)]
        ep = t["escalation"]["pass_rate"]
        en = t["escalation"]["n"]
        esc_str = f"{int(ep*en)}/{en} {'PASS' if ep == 1.0 else 'FAIL'}"
        print(f"  {threshold:>10.1f}  {t['avg_faithfulness']:>9.2f}  "
              f"{t['avg_answer_relevance']:>10.2f}  {t['avg_overall']:>8.2f}  {esc_str:>12}")

    if api_calls_saved:
        print(f"\n  ({api_calls_saved} API calls saved via cache)")
    print()

    # --- Save ---
    output = {
        "evaluated_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator_model": MODEL,
        "judge_model":     MODEL,
        "embedding_model": "voyage-3-lite",
        "chunk_tokens":    CHUNK_TOKENS,
        "thresholds":      judge_by_threshold,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")
