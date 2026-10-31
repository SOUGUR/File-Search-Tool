# Gemini RAG Chatbot

A multi-user RAG (Retrieval Augmented Generation) chatbot built on Google Gemini's
**File Search** tool and FastAPI. Users can chat with a shared knowledge base, upload
their own private documents, and tune chunking, retrieval and generation parameters.

## Architecture

```
Browser (index.html + script.js)
   │  X-User-Id header (anonymous per-browser workspace ID)
   ▼
FastAPI (async, N uvicorn workers)            backend/app.py
   ├─ validation of every user parameter      backend/schemas.py
   ├─ per-user rate limits                    backend/security.py
   ├─ concurrency cap + retries/backoff       backend/rag/gemini.py
   ├─ store registry + upload jobs (SQLite)   backend/db.py
   └─ Gemini API (google-genai, async)
        ├─ shared store  "my-rag-store"  ← admin CLI (backend/rag/upload_docs.py)
        └─ one private store per user    ← web uploads (backend/rag/ingest.py)
```

### Design for many users

| Concern | How it is handled |
|---|---|
| **Concurrency** | Fully async endpoints and the async Gemini client: one worker serves many users while they wait on Google. Run several workers (`WEB_CONCURRENCY`) and/or replicas. |
| **Data isolation** | Each user gets their **own File Search store**, so they can only retrieve their own chunks, whatever filter they send. Delete requests are checked against the user's store. |
| **Fast lookups** | A `user_id → store` registry (SQLite) avoids listing every store in the Google project on each request. The shared store and model list are cached. |
| **Quota protection** | Max in-flight Gemini calls per worker (`MAX_CONCURRENT_GEMINI_CALLS`); requests over the limit wait up to `GEMINI_QUEUE_TIMEOUT_S`, then get a 503. The SDK retries 408/429/5xx with exponential backoff and jitter. |
| **Abuse limits** | Per-user token-bucket rate limits for chat and uploads, max file size, max documents per user, allowed file types. |
| **Long-running indexing** | Uploads return `202` with a job ID right away. The client polls `/api/uploads/{id}` with backoff. Status comes from Google's operation, so **any worker or replica** can answer: no background threads, nothing lost on restart. |
| **Large files** | Uploads are streamed to a temp file in 1 MB chunks (never fully in memory), and the size limit is enforced while streaming. |
| **Stateless chat** | Conversation history is sent by the client, so any worker can serve any request. |
| **Ops** | `/healthz` probe, Docker `HEALTHCHECK`, non-root container, pinned dependencies, persistent volume for the registry. |

### Scaling further (beyond one host)

These are deliberately simple today. Swap them when you outgrow a single machine:

1. **Auth**: `X-User-Id` isolates users but is **not** authentication. Replace `current_user` in `backend/security.py` with JWT verification (Firebase/Auth0/Clerk…).
2. **Rate limits**: they are in memory per worker. Move them to Redis for exact limits across replicas.
3. **Registry**: SQLite is fine for one host with many workers. For multiple hosts, use Postgres (same queries in `backend/db.py`).
4. **Google quotas**: File Search store size is capped per tier (Free 1 GB, Tier 1 10 GB, Tier 2 100 GB, Tier 3 1 TB; stored size ≈ 3× the input). Watch the total size and your RPM/TPM limits.

## User-tunable parameters

All of these are validated server-side (`backend/schemas.py`) and passed to Google.

**Upload / indexing** (Documents panel → `POST /api/uploads`)

| Parameter | Google field | Range |
|---|---|---|
| Max tokens per chunk | `chunking_config.white_space_config.max_tokens_per_chunk` | 20–2048 (default 250) |
| Overlap tokens | `chunking_config.white_space_config.max_overlap_tokens` | 0–512, must be less than chunk size (default 40) |
| Display name | `display_name` | ≤ 512 chars |
| Custom metadata | `custom_metadata` (string, number or string list) | ≤ 20 entries |

**Answering** (Settings panel → `POST /api/chat`)

| Parameter | Google field | Range |
|---|---|---|
| Model | `model` | models enabled on the server |
| System instruction | `system_instruction` | ≤ 4000 chars |
| Temperature / Top-p / Top-k | `temperature` / `top_p` / `top_k` | 0–2 / 0–1 / 1–100 |
| Max output tokens | `max_output_tokens` | 1–65536 |
| Chunks to retrieve | `file_search.top_k` | 1–50 |
| Metadata filter | `file_search.metadata_filter` | e.g. `year >= 2021 AND subject = "math"` ([syntax](https://google.aip.dev/160)) |
| Sources | shared knowledge base and/or my documents | |

Operator-only (env vars): `EMBEDDING_MODEL` (only applies when a store is created), `ALLOWED_MODELS`, and the limits above. See `backend/.env.example`.

## Running it

**1. Configure.** Copy `backend/.env.example` to `backend/.env` and set `GEMINI_API_KEY` (get one at [Google AI Studio](https://aistudio.google.com/)).

**2a. Docker (recommended)**

```bash
docker compose up --build
```

**2b. Local Python 3.10+.** Run all commands from the project root:

```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --reload
```

**3. Load the shared knowledge base (optional).** Put files in `backend/data/`, then:

```bash
python -m backend.rag.upload_docs                       # defaults: chunk 250, overlap 40
python -m backend.rag.upload_docs --chunk-size 400 --overlap 50 --replace
# in Docker:  docker compose exec app python -m backend.rag.upload_docs
```

Files already in the store are skipped unless you pass `--replace`.

**4. Open http://localhost:8000.** Don't open `index.html` directly: the page must be served by the backend.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/options` | models, defaults, parameter ranges, limits |
| POST | `/api/chat` | ask a question (`ChatRequest`) |
| POST | `/api/uploads` | multipart: `file` + `options` (JSON `UploadOptions`) → 202 job |
| GET | `/api/uploads`, `/api/uploads/{job_id}` | upload job status |
| GET | `/api/documents` | the user's indexed documents |
| DELETE | `/api/documents/{name}` | delete one of the user's documents |
| GET | `/healthz` | liveness probe |

Interactive docs: http://localhost:8000/docs. Every `/api/*` call needs an `X-User-Id` header (8–64 chars of `A-Z a-z 0-9 _ -`).
