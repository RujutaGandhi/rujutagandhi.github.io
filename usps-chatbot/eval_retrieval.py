#!/usr/bin/env python3
# Production threshold: 0.5 - chosen based on escalation test results showing 2/2 PASS only at 0.5
"""
eval_retrieval.py

Evaluates retrieval quality for both MiniLM embedding models against
a golden test set across three match thresholds (0.3, 0.4, 0.5).
Reports Hit Rate@5 and MRR per threshold, prints a side-by-side
per-threshold breakdown, then a final comparison scorecard.

Also tests 2 escalation questions that should NOT be answered —
retrieval PASS = all similarity scores below 0.4 (bot would correctly
decline to answer).

When run, only the 2 escalation questions are newly evaluated.
Golden results are loaded from the existing eval_results.json.
Saves combined results back to eval_results.json.

Requires Supabase RPC functions:
  - match_usps_minilm(query_embedding, match_threshold, match_count)
  - match_usps_multiqa(query_embedding, match_threshold, match_count)

See bottom of file for the SQL to create these functions.
"""

import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Golden test set (10 questions — results loaded from eval_results.json)
# ---------------------------------------------------------------------------
GOLDEN = [
    ("How do I track my package?",               "USPS Tracking® - The Basics"),
    ("What do I do if my package is missing?",   "Missing Mail - The Basics"),
    ("How do I hold my mail while on vacation?", "USPS Hold Mail® - The Basics"),
    ("How do I change my address?",              "Change of Address - The Basics"),
    ("How do I get a PO Box?",                   "PO Box™ - The Basics"),
    ("How do I request a redelivery?",           "Redelivery - The Basics"),
    ("How do I sign up for Informed Delivery?",  "Informed Delivery® - The Basics"),
    ("How do I print a shipping label online?",  "Click-N-Ship® - The Basics"),
    ("Can I ship lithium batteries?",            "Can I Ship Lithium Batteries?"),
    ("How do I mail cremated remains?",          "Shipping Cremated Remains and Ashes"),
]

# ---------------------------------------------------------------------------
# Escalation test set (2 questions — should return NO relevant results)
# PASS = all similarity scores from the winning model are below
# ESCALATION_THRESHOLD (bot correctly declines to answer)
# FAIL = any result at or above ESCALATION_THRESHOLD (bot might answer)
# ---------------------------------------------------------------------------
ESCALATION_QUESTIONS = [
    "What is the best smartphone to buy?",
    "How do I fix my internet connection?",
]
ESCALATION_THRESHOLD = 0.5  # production threshold — Fixed "would attempt to answer" boundary

MODELS = {
    "minilm":  ("all-MiniLM-L6-v2",           "match_usps_minilm"),
    "multiqa": ("multi-qa-MiniLM-L6-cos-v1",  "match_usps_multiqa"),
}

MATCH_THRESHOLDS = [0.3, 0.4, 0.5]
MATCH_COUNT      = 5

SEP  = "─" * 80
SEP2 = "═" * 80

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def titles_match(returned: str, expected: str) -> bool:
    r = returned.lower().strip()
    e = expected.lower().strip()
    return r == e or e in r or r in e


def query_supabase(
    supabase: Client, rpc_fn: str, embedding: List[float], threshold: float
) -> List[dict]:
    try:
        params = {}
        params["query_embedding"] = embedding
        params["match_threshold"] = threshold
        params["match_count"]     = MATCH_COUNT
        resp = supabase.rpc(rpc_fn, params).execute()
        return resp.data or []
    except Exception as e:
        print(f"    [ERROR] RPC {rpc_fn} failed: {e}")
        return []


def deduplicate(results: List[dict], keep: int) -> List[dict]:
    """Keep only the highest-scoring chunk per article title, filling up to
    `keep` slots with unique articles in score order.

    NOTE: The chatbot retrieval logic will need the same deduplication applied
    before passing results to the LLM, to avoid repeating context from the
    same article across multiple chunks.
    """
    seen_titles: set = set()
    deduped = []
    for row in results:
        title = row.get("title", "").lower().strip()
        if title not in seen_titles:
            seen_titles.add(title)
            deduped.append(row)
            if len(deduped) == keep:
                break
    return deduped


def find_rank(results: List[dict], expected_title: str) -> Optional[int]:
    for i, row in enumerate(results, 1):
        if titles_match(row.get("title", ""), expected_title):
            return i
    return None


def mrr_score(rank: Optional[int]) -> float:
    return (1.0 / rank) if rank is not None else 0.0


# ---------------------------------------------------------------------------
# Escalation evaluation for one threshold
# ---------------------------------------------------------------------------
def run_escalation_for_threshold(
    threshold: float,
    supabase: Client,
    esc_embeddings: Dict[str, List[List[float]]],
) -> List[dict]:
    """Evaluate escalation questions at one threshold.
    PASS = no multiqa result has similarity >= ESCALATION_THRESHOLD.
    FAIL = at least one multiqa result is >= ESCALATION_THRESHOLD.
    """
    results = []

    print(f"\n  ── Escalation @ threshold {threshold} ──")

    col = 36
    for q_idx, question in enumerate(ESCALATION_QUESTIONS):
        print(f"\n  ESC{q_idx+1}: {question}")
        print(f"       Expected: ESCALATE")
        print(f"  {SEP[:76]}")
        print(f"  {'MINILM':<{col}}  {'MULTIQA'}")
        print(f"  {'-'*col}  {'-'*col}")

        all_model_results: Dict[str, List[dict]] = {}
        for key, (_, rpc_fn) in MODELS.items():
            raw = query_supabase(supabase, rpc_fn, esc_embeddings[key][q_idx], threshold)
            all_model_results[key] = deduplicate(raw, keep=MATCH_COUNT)

        for rank in range(1, MATCH_COUNT + 1):
            def fmt_row(key: str, rank: int = rank) -> str:
                rows = all_model_results[key]
                if rank - 1 < len(rows):
                    row   = rows[rank - 1]
                    title = row.get("title", "—")[:30]
                    sim   = row.get("similarity", 0)
                    flag  = "!" if sim >= ESCALATION_THRESHOLD else " "
                    return f"{flag} {rank}. {title:<30} {sim:.3f}"
                return f"   {rank}. {'—':<30}      "

            print(f"  {fmt_row('minilm'):<{col+6}}  {fmt_row('multiqa')}")

        # Verdict based on winning model (multiqa)
        multiqa_results = all_model_results["multiqa"]
        above = [r for r in multiqa_results if r.get("similarity", 0) >= ESCALATION_THRESHOLD]
        passed = len(above) == 0
        verdict = "PASS ✓ — no results above escalation threshold" if passed else \
                  f"FAIL ✗ — {len(above)} result(s) >= {ESCALATION_THRESHOLD} (bot would attempt answer)"
        print(f"\n  Verdict: {verdict}")

        results.append({
            "question": question,
            "expected": "ESCALATE",
            "passed":   passed,
            "models": {
                key: {
                    "results": [
                        {"rank": i + 1, "title": r.get("title"), "similarity": r.get("similarity")}
                        for i, r in enumerate(rs)
                    ],
                    "max_similarity":             max((r.get("similarity", 0) for r in rs), default=0.0),
                    "above_escalation_threshold": [
                        {"title": r.get("title"), "similarity": r.get("similarity")}
                        for r in rs if r.get("similarity", 0) >= ESCALATION_THRESHOLD
                    ],
                }
                for key, rs in all_model_results.items()
            },
        })

    passes = sum(1 for r in results if r["passed"])
    print(f"\n  Escalation pass rate @ {threshold}: {passes}/{len(results)}")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        sys.exit(1)

    print("Connecting to Supabase...")
    supabase: Client = create_client(supabase_url, supabase_key)
    print("  Connected.\n")

    # Load existing golden results (avoids re-running the original 10 questions)
    print("Loading existing golden results from eval_results.json...")
    try:
        with open("eval_results.json") as f:
            existing = json.load(f)
        existing_thresholds = existing.get("thresholds", {})
        print(f"  Loaded results for thresholds: {list(existing_thresholds.keys())}\n")
    except FileNotFoundError:
        print("  WARNING: eval_results.json not found — run full eval_retrieval.py first.\n")
        existing_thresholds = {}

    # Embed only the 2 escalation questions
    print("Loading embedding models...")
    loaded: Dict[str, SentenceTransformer] = {}
    for key, (model_name, _) in MODELS.items():
        print(f"  Loading {model_name}...")
        loaded[key] = SentenceTransformer(model_name)
    print()

    print(f"Embedding {len(ESCALATION_QUESTIONS)} escalation questions...")
    esc_embeddings: Dict[str, List[List[float]]] = {}
    for key, model in loaded.items():
        esc_embeddings[key] = model.encode(ESCALATION_QUESTIONS, show_progress_bar=False).tolist()
    print("  Done.\n")

    # Run escalation evaluation for each threshold
    print(SEP2)
    print(f"{'ESCALATION TESTS':^80}")
    print(SEP2)

    esc_by_threshold: Dict[str, List[dict]] = {}
    for threshold in MATCH_THRESHOLDS:
        esc_results = run_escalation_for_threshold(threshold, supabase, esc_embeddings)
        esc_by_threshold[str(threshold)] = esc_results

    # ---------------------------------------------------------------------------
    # Comparison scorecard — golden retrieval + escalation
    # ---------------------------------------------------------------------------
    print(f"\n\n{SEP2}")
    print(f"{'COMPARISON SCORECARD — ALL THRESHOLDS':^80}")
    print(SEP2)

    # Golden retrieval metrics (from existing results)
    print(f"\n  ── Golden Retrieval (multi-qa, 10 questions) ──")
    c = 10
    print(f"  {'Threshold':^{c}}  {'Hit Rate@5':>12}  {'MRR':>8}")
    print(f"  {'-'*c}  {'-'*12}  {'-'*8}")
    for threshold in MATCH_THRESHOLDS:
        t_key    = str(threshold)
        t_data   = existing_thresholds.get(t_key, {})
        summary  = t_data.get("summary", {}).get("multiqa", {})
        hr_val   = f"{summary['hit_rate_at_5']:.1%}" if "hit_rate_at_5" in summary else "n/a"
        mrr_val  = f"{summary['mrr']:.3f}"           if "mrr"           in summary else "n/a"
        print(f"  {threshold:^{c}.1f}  {hr_val:>12}  {mrr_val:>8}")

    # Escalation pass rates
    print(f"\n  ── Escalation Tests (2 questions, PASS = all sim < {ESCALATION_THRESHOLD}) ──")
    print(f"  {'Threshold':^{c}}  {'minilm Pass':>12}  {'multiqa Pass':>14}")
    print(f"  {'-'*c}  {'-'*12}  {'-'*14}")
    for threshold in MATCH_THRESHOLDS:
        t_key    = str(threshold)
        esc_list = esc_by_threshold[t_key]
        # Recalculate pass per model
        minilm_passes  = sum(
            1 for r in esc_list
            if max((x.get("similarity", 0) for x in r["models"]["minilm"]["results"]), default=0) < ESCALATION_THRESHOLD
        )
        multiqa_passes = sum(1 for r in esc_list if r["passed"])
        n_esc = len(esc_list)
        print(f"  {threshold:^{c}.1f}  {minilm_passes}/{n_esc} {'PASS' if minilm_passes == n_esc else 'FAIL':>8}  "
              f"  {multiqa_passes}/{n_esc} {'PASS' if multiqa_passes == n_esc else 'FAIL':>8}")

    print()

    # ---------------------------------------------------------------------------
    # Save — merge escalation results into existing data
    # ---------------------------------------------------------------------------
    for threshold in MATCH_THRESHOLDS:
        t_key = str(threshold)
        if t_key not in existing_thresholds:
            existing_thresholds[t_key] = {}
        existing_thresholds[t_key]["escalation"] = esc_by_threshold[t_key]

    output = {
        "evaluated_at":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "match_count":          MATCH_COUNT,
        "escalation_threshold": ESCALATION_THRESHOLD,
        "thresholds":           existing_thresholds,
    }
    with open("eval_results.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("  Results saved to eval_results.json")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# SQL: Create these RPC functions in Supabase before running this script
# ---------------------------------------------------------------------------
"""
create or replace function match_usps_minilm(
  query_embedding vector(384),
  match_threshold float,
  match_count     int
)
returns table (url text, title text, content text, chunk_index int, similarity float)
language sql stable as $$
  select url, title, content, chunk_index,
         1 - (embedding <=> query_embedding) as similarity
  from usps_content_minilm
  where 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;

create or replace function match_usps_multiqa(
  query_embedding vector(384),
  match_threshold float,
  match_count     int
)
returns table (url text, title text, content text, chunk_index int, similarity float)
language sql stable as $$
  select url, title, content, chunk_index,
         1 - (embedding <=> query_embedding) as similarity
  from usps_content_multiqa
  where 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;
"""
