# USPS Chatbot V1

A RAG-powered conversational AI agent that answers USPS customer service questions using real USPS FAQ content, with graceful escalation when it can't help.

**Live demo:** [rujutagandhi.github.io/usps-chatbot](https://rujutagandhi.github.io/usps-chatbot/)  
**Portfolio:** [rujutagandhi.github.io](https://rujutagandhi.github.io)

---

## Architecture

```
User Message
     │
     ▼
┌─────────────────────────────────────┐
│         GitHub Pages Frontend        │
│  (usps-chatbot/index.html)           │
│  - Chat UI                           │
│  - Starter question chips            │
│  - Source URL on every answer        │
└──────────────┬──────────────────────┘
               │ POST /chat
               ▼
┌─────────────────────────────────────┐
│         FastAPI Backend              │
│  (Render free tier)                  │
│  app.py → agent.py                   │
│  - POST /chat                        │
│  - GET  /health                      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│         Claude Sonnet 4 Agent        │
│  Tools:                              │
│  1. search_usps_knowledge            │
│  2. escalate_to_human                │
└──────┬───────────────────┬──────────┘
       │                   │
       ▼                   ▼
┌────────────┐    ┌─────────────────┐
│  Supabase  │    │  Anthropic API  │
│  pgvector  │    │  (Claude LLM)   │
│  664 chunks│    └─────────────────┘
└────────────┘
       ▲
       │ embed at scrape time
       │
┌─────────────────────────────────────┐
│  Voyage AI Embeddings API            │
│  voyage-3                            │
│  (1024 dimensions)                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Firecrawl                           │
│  286 USPS FAQ articles scraped       │
│  faq.usps.com/s/ (JS-rendered)       │
└─────────────────────────────────────┘
```

---

## Build Steps

The system prompt was designed before running any evaluations. Evals measure the full system — if the prompt changes after evals run, the results no longer reflect what is deployed.

| Step | What | Why at this point |
|------|------|-------------------|
| 1 | Scrape with Firecrawl | Acquire raw knowledge base |
| 2 | Clean & chunk content | Prepare for embedding |
| 3 | Embed & store in Supabase pgvector | Build the searchable vector index |
| 4 | Design system prompt | Lock agent behavior before measuring it |
| 5 | Run retrieval evals (Hit Rate@5, MRR, escalation) | Validate search quality with prompt in place |
| 6 | Run LLM-as-judge evals (faithfulness, relevance) | Validate answer quality end-to-end |
| 7 | Build agent (Claude, tools, threshold) | Decisions confirmed by evals, now build |
| 8 | Build backend (FastAPI, health endpoint) | Wrap agent for web access |
| 9 | Build frontend UI | User-facing chat interface |
| 10 | Deploy (Render + Voyage embeddings) | Voyage chosen to eliminate local model memory constraints |
| 11 | Keep-alive (cron-job.org) | Prevent cold starts on Render free tier |

---

## Product Requirements

### Problem Statement
USPS customers frequently cannot find answers to their questions even though the information exists in USPS FAQ documentation. The opportunity: an AI agent that answers accurately from trusted content and knows when to escalate.

### Core Requirements
| # | Requirement | Status |
|---|-------------|--------|
| 1 | Answer USPS FAQ questions from real USPS content | ✅ |
| 2 | Never hallucinate — ground all answers in retrieved content | ✅ |
| 3 | Escalate gracefully when confidence is low | ✅ |
| 4 | Link to source article for every answer | ✅ |
| 5 | Work on mobile and desktop | ✅ |
| 6 | No cold start delay for users | ✅ (cron keep-alive) |
| 7 | Plain text responses — no markdown formatting | ✅ |

### Out of Scope (V1)
- Multi-turn conversation memory
- Streaming responses
- Authentication or user accounts
- Real USPS system integration (tracking lookups, account changes)

---

## Retrieval Evaluation Results

Evaluated voyage-3 on a 20-question golden test set (10 common + 5 niche + 5 escalation) across three similarity thresholds. The eval uses the production system prompt so scores reflect the actual deployed system.

| Threshold | Hit Rate@5 | MRR | Escalation |
|-----------|-----------|-----|------------|
| 0.3 | **100.0%** | **0.867** | 5/5 ✅ |
| 0.4 | 93.3% | 0.833 | 5/5 ✅ |
| 0.5 | 93.3% | 0.833 | 5/5 ✅ |

**Production threshold: 0.3** — best retrieval quality with clean escalation pass.

### LLM-as-Judge Results (Claude grading Claude) at threshold 0.3

| Dimension | Score |
|-----------|-------|
| Faithfulness | 4.93 / 5.0 |
| Answer Relevance | 4.73 / 5.0 |
| Overall | 4.73 / 5.0 |
| Escalation | 5/5 PASS |

### Embedding Model Decision
Started with voyage-3-lite (512 dimensions). Common questions like "How do I track my package?" returned no results above threshold — unacceptable for the most frequent real-world queries. Switched to voyage-3 (1024 dimensions), which restored 100% Hit Rate and improved MRR from 0.825 (original MiniLM baseline) to 0.867.

---

## Tech Stack

| Layer | Tool | Why |
|-------|------|-----|
| Scraping | Firecrawl | USPS FAQs are JS-rendered (Salesforce Experience Cloud) — BeautifulSoup returns empty pages |
| Embedding | Voyage AI `voyage-3` | API-based, no local model, fits Render free tier; 100% Hit Rate@5 at threshold 0.3 |
| Vector DB | Supabase pgvector | Free tier, Postgres-native, no extra service to manage |
| LLM | Claude Sonnet 4 | Strong instruction following, tool use, low hallucination |
| Agent framework | Custom Python (no LangChain) | Full control, fewer dependencies, easier to debug |
| Backend | FastAPI + Render | Lightweight, fast startup, free tier |
| Frontend | Vanilla HTML/CSS/JS | No build step, GitHub Pages compatible |
| Keep-alive | cron-job.org | Prevents Render free tier 50s cold starts |

---

## Project Structure

```
usps-chatbot/
├── app.py                  # FastAPI server (POST /chat, GET /health)
├── agent.py                # Claude agent with search + escalate tools
├── embed_usps.py           # Chunking + embedding pipeline
├── scrape_usps.py          # Firecrawl scraping script
├── clean_usps.py           # Post-scrape content cleaning
├── eval_retrieval.py       # Hit Rate@5 + MRR retrieval evals (20 questions)
├── eval_llm_judge.py       # LLM-as-judge evaluation (production prompt)
├── eval_results.json       # Retrieval eval output
├── eval_judge_results.json # LLM judge eval output
├── usps_raw.json           # Raw scraped content (286 articles)
├── usps_cleaned.json       # Cleaned content post-processing
├── requirements.txt        # Python dependencies
├── render.yaml             # Render deployment config
└── index.html              # Chat UI frontend
```

---

## Key Product Decisions

**1. Firecrawl over BeautifulSoup**  
USPS FAQs are served by Salesforce Experience Cloud, which renders content in JavaScript. BeautifulSoup fetches raw HTML before JS executes and returns empty pages. Firecrawl handles this automatically.

**2. Supabase pgvector over Pinecone**  
Pinecone is purpose-built for vectors but adds another service, another account, and another cost. Supabase pgvector runs inside an existing Postgres instance — simpler, free, and sufficient for 664 chunks.

**3. Voyage AI over local sentence-transformers**  
sentence-transformers + PyTorch requires ~700MB RAM at startup — exceeding Render free tier's 512MB limit. Voyage API replaces the local model with a lightweight API call. No memory issue, no PyTorch, and voyage-3 outperformed the original MiniLM baseline on every eval metric.

**4. voyage-3 over voyage-3-lite**  
voyage-3-lite (512 dimensions) failed on the most common USPS queries — "How do I track my package?" returned nothing above threshold. voyage-3 (1024 dimensions) restored 100% Hit Rate. The quality difference justified the slightly higher cost ($0.06 vs $0.02 per million tokens — negligible at portfolio demo traffic).

**5. Similarity threshold 0.3**  
Chosen empirically after running evals across thresholds 0.3, 0.4, and 0.5. Threshold 0.3 achieved the best retrieval quality (100% Hit Rate, MRR 0.867) while passing all 5 escalation tests. voyage-3's precision meant lower thresholds no longer caused false-confidence answers on out-of-scope questions.

**6. Plain text responses, 3-4 sentences max**  
Claude's default markdown formatting (bold, bullets, numbered lists) rendered as raw text in the chat UI. Rather than adding a markdown parser to the frontend, the system prompt instructs Claude to respond in plain sentences with a source URL link. Cleaner for users, simpler architecture.

**7. User-first UI design**  
PM context (architecture, evals, confidence scores) belongs on the portfolio card, not in the demo. The chatbot UI is designed to feel like a real product, not a demo.

---

## Running Locally

```bash
# 1. Clone
git clone https://github.com/RujutaGandhi/rujutagandhi.github.io
cd rujutagandhi.github.io/usps-chatbot

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Add ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY, VOYAGEAI_API_KEY

# 4. Run backend
uvicorn app:app --reload --port 8000

# 5. Open frontend
# Open usps-chatbot/index.html in your browser
# Update BACKEND_URL in index.html to http://localhost:8000
```

---

## V2 Roadmap

- **Streaming responses** — more natural, real-time chat feel
- **Conversation memory** — follow-up questions work across turns
- **Article summarization** — summarize retrieved chunks before passing to LLM, improving answer quality and reducing token usage
- **Clarifying questions** — when a query is ambiguous, ask one follow-up before retrieving
- **Incremental re-scraping** — keep knowledge base fresh as USPS updates content

---

## Key Learnings

1. Check your stack's memory footprint before choosing a host — sentence-transformers + PyTorch exceeds Render free tier's 512MB limit; switching to Voyage API eliminated the local model entirely
2. Don't pick the lite/cheap model without running evals first — voyage-3-lite failed on the most common USPS queries; data revealed the problem, not assumption
3. Check third-party API batch limits before writing code — Voyage's 32k token-per-batch limit requires batch size of 16 chunks, not 128
4. Design the system prompt before running evals — evals measure the full system; changing the prompt after invalidates results
5. Verify golden set labels against the actual knowledge base — "damaged package claim" maps to "Domestic Claims", not "Missing Mail"; fixing a wrong label is not gaming the eval
6. Make all foundational decisions — DB schema, hosting, eval framework, system prompt — at architecture time before writing feature code
7. Include escalation test cases in your golden set from day one — they reveal threshold problems that success-only tests miss

---

*Built by Rujuta Gandhi · March 2026 · [rujutagandhi.github.io](https://rujutagandhi.github.io)*
