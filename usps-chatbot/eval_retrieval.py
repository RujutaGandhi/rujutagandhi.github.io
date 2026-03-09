#!/usr/bin/env python3
"""
eval_retrieval.py

Evaluates retrieval quality for both MiniLM embedding models against
a golden test set. Reports Hit Rate@5 and MRR, prints a side-by-side
comparison per question, and saves full results to eval_results.json.

Requires Supabase RPC functions:
  - match_usps_content_minilm(query_embedding, match_threshold, match_count)
  - match_usps_content_multiqa(query_embedding, match_threshold, match_count)

See bottom of file for the SQL to create these functions.
"""

import json
import os
import sys
import time
from typing import List, Optional

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Golden test set
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

MODELS = {
    "minilm":  ("all-MiniLM-L6-v2",           "match_usps_minilm"),
    "multiqa": ("multi-qa-MiniLM-L6-cos-v1",  "match_usps_multiqa"),
}

MATCH_THRESHOLD = 0.3
MATCH_COUNT     = 5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def titles_match(returned: str, expected: str) -> bool:
    """Case-insensitive substring match to handle minor ® / ™ differences."""
    r = returned.lower().strip()
    e = expected.lower().strip()
    return r == e or e in r or r in e


def query_supabase(supabase: Client, rpc_fn: str, embedding: List[float]) -> List[dict]:
    try:
        params = {}
        params["query_embedding"] = embedding
        params["match_threshold"] = MATCH_THRESHOLD
        params["match_count"] = MATCH_COUNT
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
    seen_titles = set()
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
    """Return 1-based rank of expected title, or None if not found."""
    for i, row in enumerate(results, 1):
        if titles_match(row.get("title", ""), expected_title):
            return i
    return None


def mrr_score(rank: Optional[int]) -> float:
    return (1.0 / rank) if rank is not None else 0.0

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
    print(f"  Connected.\n")

    print("Loading embedding models...")
    loaded = {}
    for key, (model_name, _) in MODELS.items():
        print(f"  Loading {model_name}...")
        loaded[key] = SentenceTransformer(model_name)
    print()

    # Embed all questions with both models upfront
    print("Embedding questions...")
    embeddings = {}
    questions = [q for q, _ in GOLDEN]
    for key, model in loaded.items():
        embeddings[key] = model.encode(questions, show_progress_bar=False).tolist()
    print(f"  Done ({len(questions)} questions × {len(MODELS)} models).\n")

    # Run retrieval
    per_question_results = []  # one entry per question
    model_stats = {k: {"hits": 0, "mrr_sum": 0.0} for k in MODELS}

    SEP  = "─" * 80
    SEP2 = "═" * 80

    print(SEP2)
    print(f"{'RETRIEVAL EVALUATION':^80}")
    print(SEP2)

    for q_idx, (question, expected) in enumerate(GOLDEN):
        print(f"\nQ{q_idx+1}: {question}")
        print(f"     Expected: \"{expected}\"")
        print(SEP)

        q_data = {"question": question, "expected": expected, "models": {}}

        # Header row
        col = 36
        print(f"  {'MINILM (all-MiniLM-L6-v2)':<{col}}  {'MULTIQA (multi-qa-MiniLM-L6-cos-v1)'}")
        print(f"  {'-'*(col)}  {'-'*(col)}")

        results_by_model = {}
        for key, (_, rpc_fn) in MODELS.items():
            emb = embeddings[key][q_idx]
            raw = query_supabase(supabase, rpc_fn, emb)
            results_by_model[key] = deduplicate(raw, keep=MATCH_COUNT)

        # Print side-by-side (up to MATCH_COUNT rows)
        for rank in range(1, MATCH_COUNT + 1):
            def fmt_row(key):
                rows = results_by_model[key]
                if rank - 1 < len(rows):
                    row = rows[rank - 1]
                    title = row.get("title", "—")[:30]
                    sim   = row.get("similarity", 0)
                    hit   = "✓" if titles_match(row.get("title", ""), expected) else " "
                    return f"{hit} {rank}. {title:<30} {sim:.3f}"
                return f"   {rank}. {'—':<30}      "

            left  = fmt_row("minilm")
            right = fmt_row("multiqa")
            print(f"  {left:<{col+6}}  {right}")

        # Compute metrics
        for key in MODELS:
            results = results_by_model[key]
            actual_rank = find_rank(results, expected)
            hit = actual_rank is not None
            mrr = mrr_score(actual_rank)
            model_stats[key]["hits"]    += int(hit)
            model_stats[key]["mrr_sum"] += mrr

            q_data["models"][key] = {
                "results": [
                    {"rank": i+1, "title": r.get("title"), "similarity": r.get("similarity")}
                    for i, r in enumerate(results)
                ],
                "hit":  hit,
                "rank": actual_rank,
                "mrr":  mrr,
            }

        per_question_results.append(q_data)

    # ---------------------------------------------------------------------------
    # Final scorecard
    # ---------------------------------------------------------------------------
    n = len(GOLDEN)
    print(f"\n{SEP2}")
    print(f"{'FINAL SCORECARD':^80}")
    print(SEP2)
    print(f"\n  {'Metric':<20}  {'all-MiniLM-L6-v2':>20}  {'multi-qa-MiniLM-L6-cos-v1':>26}")
    print(f"  {'-'*18}  {'-'*20}  {'-'*26}")

    summary = {}
    for key, (model_name, _) in MODELS.items():
        hit_rate = model_stats[key]["hits"] / n
        mrr      = model_stats[key]["mrr_sum"] / n
        summary[key] = {"model": model_name, "hit_rate_at_5": hit_rate, "mrr": mrr}

    hit_row = f"  {'Hit Rate@5':<20}  {summary['minilm']['hit_rate_at_5']:>19.1%}  {summary['multiqa']['hit_rate_at_5']:>25.1%}"
    mrr_row = f"  {'MRR':<20}  {summary['minilm']['mrr']:>20.3f}  {summary['multiqa']['mrr']:>26.3f}"
    print(hit_row)
    print(mrr_row)
    print()

    winner_hr  = max(MODELS, key=lambda k: summary[k]["hit_rate_at_5"])
    winner_mrr = max(MODELS, key=lambda k: summary[k]["mrr"])
    print(f"  Best Hit Rate@5 : {MODELS[winner_hr][0]}")
    print(f"  Best MRR        : {MODELS[winner_mrr][0]}")
    print()

    # ---------------------------------------------------------------------------
    # Save results
    # ---------------------------------------------------------------------------
    output = {
        "evaluated_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "match_threshold": MATCH_THRESHOLD,
        "match_count":     MATCH_COUNT,
        "summary":         summary,
        "questions":       per_question_results,
    }
    with open("eval_results.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("  Full results saved to eval_results.json")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# SQL: Create these RPC functions in Supabase before running this script
# ---------------------------------------------------------------------------
"""
-- Run once for each table:

create or replace function match_usps_content_minilm(
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

create or replace function match_usps_content_multiqa(
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
