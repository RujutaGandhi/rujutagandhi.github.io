#!/usr/bin/env python3
"""
embed_usps.py

Reads usps_cleaned.json, chunks each article into 500-token pieces
with 50-token overlap, generates embeddings using Voyage AI API,
and uploads to Supabase table usps_content_voyage.

Table:
  - usps_content_voyage  (voyage-lite-02-instruct, 1024 dimensions)
"""

import json
import os
import sys
import time

import voyageai
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_FILE   = "usps_cleaned.json"
CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
BATCH_SIZE   = 50    # rows per Supabase upsert call
VOYAGE_BATCH = 16    # Conservative batch size to handle longer chunks staying under 32k token limit
TABLE        = "usps_content_voyage"
VOYAGE_MODEL = "voyage-3"

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk_text(text: str, chunk_size: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    tokens = text.split()
    if not tokens:
        return []
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunks.append(" ".join(tokens[start:end]))
        if end >= len(tokens):
            break
        start += chunk_size - overlap
    return chunks

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

    # Connect
    print("Connecting to Supabase...")
    supabase: Client = create_client(supabase_url, supabase_key)
    print(f"  Connected to {supabase_url}")

    print("Connecting to Voyage AI...")
    vo = voyageai.Client(api_key=voyage_key)
    print(f"  Using model: {VOYAGE_MODEL}\n")

    # Load articles
    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        data = json.load(f)
    articles = data["pages"]
    print(f"  {len(articles)} articles loaded.\n")

    # Build all chunks
    print("Chunking articles...")
    chunks = []
    for article in articles:
        for i, chunk in enumerate(chunk_text(article["content"])):
            chunks.append({
                "url":         article["url"],
                "title":       article["title"],
                "chunk_index": i,
                "content":     chunk,
            })
    print(f"  {len(chunks)} total chunks from {len(articles)} articles.\n")

    # Embed in Voyage batches, upload in Supabase batches
    print(f"Embedding and uploading to {TABLE}...")
    total    = len(chunks)
    uploaded = 0
    failed   = 0

    for v_start in range(0, total, VOYAGE_BATCH):
        v_batch = chunks[v_start:v_start + VOYAGE_BATCH]
        texts   = [c["content"] for c in v_batch]

        # Embed via Voyage API
        try:
            result     = vo.embed(texts, model=VOYAGE_MODEL, input_type="document")
            embeddings = result.embeddings
        except Exception as e:
            print(f"  [ERROR] Voyage embed failed at batch {v_start}: {e}")
            failed += len(v_batch)
            continue

        # Upload to Supabase in sub-batches
        rows = [
            {
                "url":         c["url"],
                "title":       c["title"],
                "chunk_index": c["chunk_index"],
                "content":     c["content"],
                "embedding":   emb,
            }
            for c, emb in zip(v_batch, embeddings)
        ]

        for s_start in range(0, len(rows), BATCH_SIZE):
            s_batch = rows[s_start:s_start + BATCH_SIZE]
            try:
                supabase.table(TABLE).upsert(s_batch).execute()
                uploaded += len(s_batch)
            except Exception as e:
                print(f"  [WARN] Batch upsert failed ({e}), retrying row-by-row...")
                for row in s_batch:
                    try:
                        supabase.table(TABLE).upsert(row).execute()
                        uploaded += 1
                    except Exception as row_err:
                        print(f"  [ERROR] Row failed (url={row['url']}, chunk={row['chunk_index']}): {row_err}")
                        failed += 1

        print(f"  [{min(v_start + VOYAGE_BATCH, total)}/{total}] uploaded {uploaded}, failed {failed}")

    print(f"\nDone — {uploaded} rows uploaded, {failed} failed.")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")
