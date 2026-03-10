#!/usr/bin/env python3
"""
eval_retrieval.py

Evaluates retrieval quality for the Voyage voyage-3-lite embedding model
against a golden test set across three match thresholds (0.3, 0.4, 0.5).
Reports Hit Rate@5 and MRR per threshold.

Also tests 2 escalation questions that should NOT be answered —
PASS = all similarity scores below ESCALATION_THRESHOLD (0.5).

Requires Supabase RPC function:
  - match_usps_voyage(query_embedding vector(512), match_threshold float, match_count int)

Saves results to eval_results.json.
"""

import json
import os
import sys
import time
from typing import Dict, List, Optional

import voyageai
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
VOYAGE_MODEL         = "voyage-3"
RPC_FUNCTION         = "match_usps_voyage"
MATCH_THRESHOLDS     = [0.3, 0.4, 0.5]
MATCH_COUNT          = 5
ESCALATION_THRESHOLD = 0.5

SEP  = "─" * 80
SEP2 = "═" * 80

# ---------------------------------------------------------------------------
# Golden test set — 10 common + 5 niche
# ---------------------------------------------------------------------------
GOLDEN = [
    # Common
    ("How do I track my package?",                        "USPS Tracking® - The Basics"),
    ("What do I do if my package is missing?",            "Missing Mail - The Basics"),
    ("How do I hold my mail while on vacation?",          "USPS Hold Mail® - The Basics"),
    ("How do I change my address?",                       "Change of Address - The Basics"),
    ("How do I get a PO Box?",                            "PO Box™ - The Basics"),
    ("How do I request a redelivery?",                    "Redelivery - The Basics"),
    ("How do I sign up for Informed Delivery?",           "Informed Delivery® - The Basics"),
    ("How do I print a shipping label online?",           "Click-N-Ship® - The Basics"),
    ("Can I ship lithium batteries?",                     "Can I Ship Lithium Batteries?"),
    ("How do I mail cremated remains?",                   "Shipping Cremated Remains and Ashes"),
    # Niche
    ("How do I send a money order?",                      "Money Orders - The Basics"),
    ("What are the size restrictions for mailing a package?", "Parcel Size, Weight & Fee Standards"),
    ("How do I file a claim for a damaged package?",      "Domestic Claims - The Basics"),
    ("How do I send certified mail?",                     "Certified Mail® - The Basics"),
    ("What is USPS Media Mail and what can I ship with it?", "What is Media Mail®?"),
]

ESCALATION_QUESTIONS = [
    "What is the best smartphone to buy?",
    "How do I fix my internet connection?",
    "Can you help me file my taxes?",
    "How do I dispute a charge on my credit card?",
    "What is the weather forecast for tomorrow?",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def titles_match(returned: str, expected: str) -> bool:
    r = returned.lower().strip()
    e = expected.lower().strip()
    return r == e or e in r or r in e


def query_supabase(supabase: Client, embedding: List[float], threshold: float) -> List[dict]:
    try:
        resp = supabase.rpc(RPC_FUNCTION, {
            "query_embedding": embedding,
            "match_threshold":  threshold,
            "match_count":      MATCH_COUNT,
        }).execute()
        return resp.data or []
    except Exception as e:
        print(f"    [ERROR] RPC failed: {e}")
        return []


def deduplicate(results: List[dict], keep: int) -> List[dict]:
    seen: set = set()
    deduped = []
    for row in results:
        title = row.get("title", "").lower().strip()
        if title not in seen:
            seen.add(title)
            deduped.append(row)
            if len(deduped) == keep:
                break
    return deduped


def find_rank(results: List[dict], expected_title: str) -> Optional[int]:
    for i, row in enumerate(results, 1):
        if titles_match(row.get("title", ""), expected_title):
            return i
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    voyage_key   = os.getenv("VOYAGEAI_API_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        sys.exit(1)
    if not voyage_key:
        print("ERROR: VOYAGEAI_API_KEY must be set in .env")
        sys.exit(1)

    print("Connecting to Supabase...")
    supabase: Client = create_client(supabase_url, supabase_key)
    print("  Connected.")

    print("Connecting to Voyage AI...")
    vo = voyageai.Client(api_key=voyage_key)
    print(f"  Model: {VOYAGE_MODEL}\n")

    # Embed all questions
    all_questions = [q for q, _ in GOLDEN] + ESCALATION_QUESTIONS
    print(f"Embedding {len(all_questions)} questions...")
    result = vo.embed(all_questions, model=VOYAGE_MODEL, input_type="query")
    all_embeddings = result.embeddings
    golden_embeddings   = all_embeddings[:len(GOLDEN)]
    escalation_embeddings = all_embeddings[len(GOLDEN):]
    print("  Done.\n")

    results_by_threshold: Dict[str, dict] = {}

    for threshold in MATCH_THRESHOLDS:
        print(SEP2)
        print(f"  THRESHOLD: {threshold}")
        print(SEP2)

        # --- Golden retrieval ---
        hits = 0
        mrr_total = 0.0
        question_results = []

        print(f"\n  {'#':<4} {'Question':<45} {'Rank':>5}  {'Top Result'}")
        print(f"  {'-'*4} {'-'*45} {'-'*5}  {'-'*30}")

        for i, ((question, expected_title), embedding) in enumerate(zip(GOLDEN, golden_embeddings), 1):
            raw = query_supabase(supabase, embedding, threshold)
            results = deduplicate(raw, keep=MATCH_COUNT)
            rank = find_rank(results, expected_title)

            hit = rank is not None
            mrr = (1.0 / rank) if rank else 0.0
            hits += int(hit)
            mrr_total += mrr

            top_title = results[0].get("title", "—")[:35] if results else "—"
            rank_str  = str(rank) if rank else "miss"
            marker    = "✓" if hit else "✗"
            print(f"  {i:<4} {question[:44]:<45} {marker} {rank_str:>3}  {top_title}")

            question_results.append({
                "question":       question,
                "expected_title": expected_title,
                "rank":           rank,
                "hit":            hit,
                "mrr":            mrr,
                "top_results": [
                    {"title": r.get("title"), "similarity": round(r.get("similarity", 0), 3)}
                    for r in results
                ],
            })

        n = len(GOLDEN)
        hit_rate = hits / n
        mrr_avg  = mrr_total / n
        print(f"\n  Hit Rate@5: {hit_rate:.1%}  |  MRR: {mrr_avg:.3f}  ({hits}/{n} hits)")

        # --- Escalation ---
        print(f"\n  ── Escalation Tests (PASS = all sim < {ESCALATION_THRESHOLD}) ──")
        escalation_results = []

        for j, (question, embedding) in enumerate(zip(ESCALATION_QUESTIONS, escalation_embeddings), 1):
            raw = query_supabase(supabase, embedding, threshold)
            results = deduplicate(raw, keep=MATCH_COUNT)
            above = [r for r in results if r.get("similarity", 0) >= ESCALATION_THRESHOLD]
            passed = len(above) == 0
            max_sim = max((r.get("similarity", 0) for r in results), default=0.0)
            verdict = "PASS ✓" if passed else f"FAIL ✗ ({len(above)} result(s) above threshold)"
            print(f"  ESC{j}: {question}")
            print(f"         max_sim={max_sim:.3f}  →  {verdict}\n")

            escalation_results.append({
                "question":   question,
                "expected":   "ESCALATE",
                "passed":     passed,
                "max_similarity": max_sim,
                "results": [
                    {"title": r.get("title"), "similarity": round(r.get("similarity", 0), 3)}
                    for r in results
                ],
            })

        esc_passes = sum(1 for r in escalation_results if r["passed"])
        print(f"  Escalation pass rate: {esc_passes}/{len(escalation_results)}")

        results_by_threshold[str(threshold)] = {
            "hit_rate_at_5": hit_rate,
            "mrr":           mrr_avg,
            "hits":          hits,
            "n":             n,
            "questions":     question_results,
            "escalation":    escalation_results,
            "escalation_pass_rate": esc_passes / len(escalation_results),
        }

    # --- Scorecard ---
    print(f"\n\n{SEP2}")
    print(f"{'SCORECARD — voyage-3':^80}")
    print(SEP2)
    print(f"\n  {'Threshold':>10}  {'Hit Rate@5':>12}  {'MRR':>8}  {'Escalation':>12}")
    print(f"  {'-'*10}  {'-'*12}  {'-'*8}  {'-'*12}")
    for threshold in MATCH_THRESHOLDS:
        t = results_by_threshold[str(threshold)]
        esc = f"{int(t['escalation_pass_rate']*len(t['escalation']))}/{len(t['escalation'])}"
        esc_label = "PASS" if t["escalation_pass_rate"] == 1.0 else "FAIL"
        print(f"  {threshold:>10.1f}  {t['hit_rate_at_5']:>12.1%}  {t['mrr']:>8.3f}  {esc:>6} {esc_label:>6}")
    print()

    # --- Save ---
    output = {
        "evaluated_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "embedding_model": VOYAGE_MODEL,
        "rpc_function":   RPC_FUNCTION,
        "match_count":    MATCH_COUNT,
        "escalation_threshold": ESCALATION_THRESHOLD,
        "thresholds":     results_by_threshold,
    }
    with open("eval_results.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("  Results saved to eval_results.json")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")
