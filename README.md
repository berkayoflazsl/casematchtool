# UK case law semantic search (Find Case Law)

This project is a small **local research tool** for exploring **England & Wales** judgments published in **Find Case Law** (The National Archives). You describe a situation or legal question in plain language; the app finds **chapters of judgments** that are *semantically* close to your text, and optionally adds **short explanations** of why a case might be relevant.

It is built for **exploration and triage**: pointing you toward possibly related decisions—not for replacing reading the full judgment, a qualified lawyer, or official research services.

**This is not legal advice.** Always read the source judgment and verify citations and facts.

## What it does

1. **Ingests** public metadata and judgment text from the official FCL **Atom** feed, stores cases and text chunks, and embeds them with a local **BGE** model (FastEmbed).
2. **Searches** with your query: the query is embedded the same way, and **PostgreSQL + pgvector** returns the closest chunks, collapsed to one best chunk per case, then the top *N* cases.
3. **Optionally** calls an **OpenAI-compatible** API (OpenAI, OpenRouter, etc.) to re-rank a small set of candidates, add **short summaries**, and **“why it might match”** text. You can turn the LLM off for faster, cheaper, embedding-only results.

The stack: **FastAPI** · **PostgreSQL** · **pgvector** · local embeddings · optional LLM.

## Why you might use it

- You have a **factual or legal-question** phrasing and want a **first pass** at which published judgments may touch similar issues.
- You are building a **pilot** or **integration** and need an API and database schema that start from FCL’s open data and vector search, without claiming completeness over all case law or any particular court coverage.

**What it does *not* guarantee:** It only searches **ingested** cases, not the entire FCL database. Quality depends on your corpus size, chunking, and model choice. Ranks and LLM text can be wrong; treat them as **hints**.

## Features

- CLI ingestion from the FCL Atom feed, judgment XML fetch, chunking, embeddings, and storage.
- `POST /v1/search` — semantic search with tunable candidate counts, optional LLM, and a “fast search (no LLM)” mode.
- Simple web UI: `app/static/index.html`

## Requirements

- **Python 3.11+** (tested on 3.13; no PyTorch required for the default embedder path).
- **PostgreSQL 14+** with the **pgvector** extension.
- (Optional) **OpenAI** or **OpenRouter** (or any OpenAI-compatible) API key for the LLM step.

## Setup

```bash
cd project_law
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Database migrations

```bash
psql -d project_law -f db/migrations/001_init.sql
psql -d project_law -f db/migrations/002_ingestion_hybrid_embedding.sql
```

Migration `002` adds `vector(384)`-compatible storage and `ingestion_runs` / `search_events`. If you already applied `001`, `002` may rebuild `case_chunks` for dimension alignment (**existing vectors are dropped**—plan accordingly).

## Environment variables

Create `.env` in the project root (see `.env.example`; **never** commit real secrets).

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | e.g. `postgresql://USER@localhost:5432/project_law` |
| `OPENAI_API_KEY` | OpenAI `sk-...` or OpenRouter `sk-or-...` |
| `LLM_SERVICE_URL` | e.g. OpenRouter `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | e.g. `openai/gpt-4o-mini` |
| `PORT` | Uvicorn port (default 8000) |
| `FCL_ATOM_BASE` | FCL Atom URL (default is the official one) |
| `FCL_REQUEST_SLEEP` | Delay between FCL requests (seconds), politeness |
| `SEARCH_CANDIDATE_K` / `SEARCH_FINAL_N` | Retrieval and response sizes |
| `SEARCH_LLM_MAX_CASES` / `SEARCH_LLM_EXCERPT_CHARS` / `SEARCH_LLM_TIMEOUT_SEC` / `SEARCH_LLM_MAX_OUTPUT_TOKENS` | Smaller = usually faster/cheaper LLM step |

## Ingesting data

```bash
source .venv/bin/activate
cd project_law
# Example: up to 100 new cases (not already in DB); scan up to 25 Atom pages if needed
python -m app.cli ingest --limit 100 --pages 25
```

- `--limit`: number of **new** cases to add (default 30). Existing `source_uri` values are skipped; the feed may advance to later pages to fill the limit.
- `--pages`: cap on how many Atom pages to walk.
- `--include-existing`: re-fetch and update text/embeddings for items already in the database (use with care).

FCL may rate-limit by IP. For bulk or automated collection, read [permissions and licensing](https://caselaw.nationalarchives.gov.uk/permissions-and-licensing) and respect the service.

## Run the API and UI

```bash
source .venv/bin/activate
cd project_law
uvicorn app.main:app --host 127.0.0.1 --port 8000
# or, using .env PORT:
python -m app
```

- Health: `http://127.0.0.1:8000/health`
- Web UI: `http://127.0.0.1:8000/`
- OpenAPI: `http://127.0.0.1:8000/docs`

### Example search

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"unfair dismissal whistleblowing UK","final_n":5,"candidate_k":40,"use_llm":true}'
```

Set `"use_llm": false` for embedding-only results (faster, no API cost for the LLM). If `used_llm` is `false` in the response, either the LLM was off, a key was missing, or a timeout/fallback path ran.

## How it is structured

1. **Ingestion:** Atom → judgment XML → plain text → chunks → local embeddings (e.g. `BAAI/bge-small-en-v1.5`, 384 dims) → PostgreSQL.
2. **Search:** query embedding → vector nearest neighbors → per-case best chunk → optional LLM on a small candidate list for wording and order.

## License (this codebase)

The application code in this repository is for your own licensing choice. The **judgment text** and FCL data remain subject to **National Archives / open justice** terms; comply with FCL [terms of use](https://caselaw.nationalarchives.gov.uk/terminology/terms-of-use).

## Troubleshooting

- **`Connection refused`:** server not running, or `PORT` mismatch.
- **“Set OPENAI_API_KEY...” / `used_llm: false` with LLM on:** set `OPENAI_API_KEY` (and for OpenRouter, `LLM_SERVICE_URL`); restart the app.
- **Vector dimension errors:** the embedding model in `app/embedding_model.py` must match `vector(384)` in the migrations.
- **Settings cache:** the process may need a full restart to pick up new environment variables (see Pydantic `lru_cache` on settings).

**Security:** Do not put API keys in the repo, chat logs, or screenshots. Rotate keys in your provider dashboard on a sensible schedule.
