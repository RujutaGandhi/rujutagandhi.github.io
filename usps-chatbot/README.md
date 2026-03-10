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
│  - Source citation display           │
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
│         Claude claude-sonnet-4 Agent │
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
│  sentence-transformers               │
│  multi-qa-MiniLM-L6-cos-v1          │
│  (384 dimensions)                    │
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

## Product Requirements

### Problem Statement
USPS customers frequently cannot find answers to their questions even though the information exists in USPS FAQ documentation. The opportunity: an AI agent that answers accurately from trusted content and knows when to escalate.

### Core Requirements
| # | Requirement | Status |
|---|-------------|--------|
| 1 | Answer USPS FAQ questions from real USPS content | ✅ |
| 2 | Never hallucinate — ground all answers in retrieved content | ✅ |
| 3 | Escalate gracefully when confidence is low | ✅ |
| 4 | Cite the source article for every answer | ✅ |
| 5 | Work on mobile and desktop | ✅ |
| 6 | No cold start delay for users | ✅ (cron keep-alive) |
| 7 | No to low cost | ✅ |

### Out of Scope (V1)
- Multi-turn conversation memory
- Streaming responses
- Authentication or user accounts
- Real USPS system integration (tracking lookups, account changes)

---

## Retrieval Evaluation Results

Evaluated two embedding models on a 12-question golden test set (8 Common Questions + 2 Niche Questions + 2 escalation) at similarity threshold 0.5.

| Metric | all-MiniLM-L6-v2 | multi-qa-MiniLM-L6-cos-v1 |
|--------|------------------|---------------------------|
| Hit Rate@5 | 80.0% | **100.0%** |
| MRR | 0.700 | **0.825** |
| Escalation (2/2) | ✅ | ✅ |

**Winner: multi-qa-MiniLM-L6-cos-v1**

### LLM-as-Judge Results (Claude grading Claude)

| Dimension | Score |
|-----------|-------|
| Faithfulness | 5.0 / 5.0 |
| Answer Relevance | 4.3 / 5.0 |
| Overall | 4.3 / 5.0 |

### Threshold Decision
Threshold 0.5 was selected because it is the lowest value at which both escalation test cases pass. Lower thresholds (0.3, 0.4) produced higher retrieval scores but caused the bot to answer out-of-scope questions with false confidence.

---

## Tech Stack

| Layer | Tool | Why |
|-------|------|-----|
| Scraping | Firecrawl | USPS FAQs are JS-rendered (Salesforce Experience Cloud) — BeautifulSoup returns empty pages |
| Embedding | sentence-transformers `multi-qa-MiniLM-L6-cos-v1` | Best retrieval evals; 384-dim, runs on CPU |
| Vector DB | Supabase pgvector | Free tier, Postgres-native, no extra service to manage |
| LLM | Claude claude-sonnet-4 | Strong instruction following, tool use, low hallucination |
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
├── eval_retrieval.py       # Hit Rate@5 + MRR retrieval evals
├── eval_llm_judge.py       # LLM-as-judge evaluation
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

**3. Similarity threshold 0.5**  
Chosen empirically after running escalation tests. Lower thresholds caused the bot to answer off-topic questions confidently. 0.5 is the minimum value where escalation works correctly.

**4. Render free tier + cron keep-alive**  
Render free tier spins down after 15 minutes of inactivity (50s+ cold start). A cron-job.org ping to `/health` every 10 minutes prevents spin-down at zero cost — appropriate for a portfolio demo.

**5. User-first UI design**  
PM context (architecture, evals, confidence scores) belongs on the portfolio card, not in the demo. The chatbot UI is designed to feel like a real product, not a demo.

---

## Running Locally

```bash
# 1. Clone
git clone https://github.com/RujutaGandhi/rujutagandhi.github.io
cd rujutagandhi.github.io/usps-chatbot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Add ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY

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

---

## Key Learnings

1. Design DB schema and code together — mismatches cause hard-to-debug bugs
2. Include escalation test cases in your golden set — plan for this as part of the test set
3. Deduplication is essential in chunked RAG — same article appears multiple times
4. Make foundational decisions — schema, hosting, eval framework — at architecture time, before writing any feature code.

---

*Built by Rujuta Gandhi · March 2026 · [rujutagandhi.github.io](https://rujutagandhi.github.io)*
