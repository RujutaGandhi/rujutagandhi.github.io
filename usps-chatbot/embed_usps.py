#!/usr/bin/env python3
"""
embed_usps.py

Reads usps_cleaned.json, chunks each article into 500-token pieces
with 50-token overlap, generates embeddings using two sentence-transformer
models, and uploads to two Supabase tables.

Tables:
  - usps_content_minilm    (all-MiniLM-L6-v2)
  - usps_content_multiqa   (multi-qa-MiniLM-L6-cos-v1)
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_FILE = "usps_cleaned.json"
CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
BATCH_SIZE = 50  # rows per Supabase upsert call

MODELS = {
    "usps_content_minilm":  "all-MiniLM-L6-v2",
    "usps_content_multiqa": "multi-qa-MiniLM-L6-cos-v1",
}

# ---------------------------------------------------------------------------
# Tokenizer (simple whitespace split — consistent with MiniLM's rough token count)
# ---------------------------------------------------------------------------
def tokenize(text: str) -> list[str]:
    return text.split()

def chunk_text(text: str, chunk_size: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    tokens = tokenize(text)
    if not tokens:
        return []
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk = " ".join(tokens[start:end])
        chunks.append(chunk)
        if end >= len(tokens):
            break
        start += chunk_size - overlap
    return chunks

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Load environment
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        sys.exit(1)

    # Connect to Supabase
    print("Connecting to Supabase...")
    supabase: Client = create_client(supabase_url, supabase_key)
    print(f"  Connected to {supabase_url}\n")

    # Load articles
    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        data = json.load(f)
    articles = data["pages"]
    print(f"  {len(articles)} articles loaded.\n")

    # Load models
    print("Loading embedding models...")
    loaded_models = {}
    for table, model_name in MODELS.items():
        print(f"  Loading {model_name}...")
        loaded_models[table] = SentenceTransformer(model_name)
    print()

    # Build all chunks
    print("Chunking articles...")
    chunks = []  # list of {url, title, chunk_index, content}
    for article in articles:
        url = article["url"]
        title = article["title"]
        content = article["content"]
        article_chunks = chunk_text(content)
        for i, chunk in enumerate(article_chunks):
            chunks.append({
                "url": url,
                "title": title,
                "chunk_index": i,
                "content": chunk,
            })
    print(f"  {len(chunks)} total chunks from {len(articles)} articles.\n")

    # Embed and upload for each model/table
    for table, model in loaded_models.items():
        model_name = MODELS[table]
        print(f"{'='*60}")
        print(f"Model: {model_name}  →  Table: {table}")
        print(f"{'='*60}")

        total = len(chunks)
        uploaded = 0
        failed = 0

        for batch_start in range(0, total, BATCH_SIZE):
            batch = chunks[batch_start:batch_start + BATCH_SIZE]
            texts = [c["content"] for c in batch]

            # Generate embeddings
            try:
                embeddings = model.encode(texts, show_progress_bar=False).tolist()
            except Exception as e:
                print(f"  [ERROR] Embedding batch {batch_start}–{batch_start+len(batch)}: {e}")
                failed += len(batch)
                continue

            # Build rows
            rows = []
            for chunk, embedding in zip(batch, embeddings):
                rows.append({
                    "url":         chunk["url"],
                    "title":       chunk["title"],
                    "chunk_index": chunk["chunk_index"],
                    "content":     chunk["content"],
                    "embedding":   embedding,
                })

            # Upload to Supabase
            try:
                supabase.table(table).upsert(rows).execute()
                uploaded += len(rows)
            except Exception as e:
                # Try row-by-row so one bad row doesn't lose the whole batch
                print(f"  [WARN] Batch upsert failed ({e}), retrying row-by-row...")
                for row in rows:
                    try:
                        supabase.table(table).upsert(row).execute()
                        uploaded += 1
                    except Exception as row_err:
                        print(f"  [ERROR] Row failed (url={row['url']}, chunk={row['chunk_index']}): {row_err}")
                        failed += 1

            batch_end = min(batch_start + BATCH_SIZE, total)
            print(f"  [{batch_end}/{total}] uploaded {uploaded}, failed {failed}")

        print(f"\n  Done — {uploaded} rows uploaded, {failed} failed.\n")

    print("All models complete.")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nTotal time: {time.time() - t0:.1f}s")
