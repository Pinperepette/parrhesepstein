# Parrhesepstein

<p align="center">
  <img src="icon.png" alt="Parrhesepstein" width="400">
</p>

**An AI-powered investigative platform for the Epstein Files.**

Parrhesepstein is a full-stack Flask application that enables deep, systematic analysis of the Jeffrey Epstein document corpus released by the U.S. Department of Justice. It combines multi-agent AI investigation, semantic search (RAG), network graph analysis, and structured data persistence to surface connections, financial flows, and patterns across thousands of declassified documents.

The name combines *parrhesia* (Greek: fearless speech, speaking truth to power) with *Epstein*. Name idea by **Boni Castellane**.

**Author:** [The Pirate](https://x.com/Pinperepette)

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [Core Features](#core-features)
  - [Document Search & Retrieval](#1-document-search--retrieval)
  - [Person Investigation](#2-person-investigation)
  - [Crew Investigation (Multi-Agent)](#3-crew-investigation-multi-agent)
  - [Network Graph Analysis](#5-network-graph-analysis)
  - [Influence Network Mapping](#6-influence-network-mapping)
  - [Investigation Merging & Meta-Analysis](#7-investigation-merging--meta-analysis)
  - [Report Synthesis](#8-report-synthesis)
  - [Email Dataset Search](#9-email-dataset-search)
  - [Flight Data Analysis](#10-flight-data-analysis)
  - [RAG Archive (Q&A)](#11-rag-archive-qa)
  - [Citation Fact-Checker](#12-citation-fact-checker)
- [API Reference](#api-reference)
- [Agent System](#agent-system)
- [Database Schema](#database-schema)
- [Data Pipeline](#data-pipeline)
- [License](#license)

---

## Architecture Overview

```
                          +------------------+
                          |   Flask (5001)   |
                          +--------+---------+
                                   |
              +--------------------+--------------------+
              |                    |                     |
     +--------v-------+  +--------v--------+  +---------v--------+
     |  18 Route       |  |  9 Agent        |  |  13 Service      |
     |  Blueprints     |  |  Modules        |  |  Modules         |
     |  (71 endpoints) |  |  (AI workers)   |  |  (data layer)    |
     +--------+--------+  +--------+--------+  +---------+--------+
              |                    |                      |
    +---------+---------+  +------+-------+    +---------+---------+
    |                   |  |              |    |         |         |
+---v---+  +--------+  |  | Claude API   |  +-v---+ +--v--+ +---v----+
| HTML  |  | JSON   |  |  | (Anthropic)  |  |Mongo| |Chroma| |justice |
| Pages |  | APIs   |  |  +--------------+  |DB   | |DB   | |.gov    |
+-------+  +--------+  |                    +-----+ +-----+ +--------+
                        |
               +--------v--------+
               |  Background     |
               |  Thread Pool    |
               |  (daemon jobs)  |
               +-----------------+
```

All long-running operations (investigations, network generation, PDF downloads, influence analysis) run as **background daemon threads** with polling status endpoints, keeping the UI responsive.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Flask 3.1.2, Python 3.11+ |
| AI Engine | Claude (Anthropic SDK), ThreadPoolExecutor (parallel batch analysis) |
| Vector DB | ChromaDB 0.4.18 (semantic search / RAG) |
| Document DB | MongoDB (PyMongo 4.6) |
| Graph Analysis | NetworkX 3.4.2 |
| PDF Processing | PyPDF2, PyMuPDF, Tesseract OCR, Claude Vision |
| Data Analysis | Pandas 2.3.3 |
| Frontend | Vanilla JS, Vis.js (network graphs), Leaflet.js (maps) |
| Data Source | U.S. DOJ Epstein Files (justice.gov), Epstein email dataset |

---

## Project Structure

```
parrhesepstein/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── config.py                # Centralized configuration
│   ├── extensions.py            # Shared state (MongoDB, email DF, OCR flags)
│   ├── run.py                   # Entry point
│   │
│   ├── routes/                  # 18 Blueprint modules, 71+ endpoints
│   │   ├── pages.py             # 20 HTML page routes
│   │   ├── search.py            # Search API (justice.gov, emails, semantic)
│   │   ├── documents.py         # Document management + RAG Q&A
│   │   ├── investigate.py       # Single-person investigation
│   │   ├── investigation_crew.py # Multi-agent crew system
│   │   ├── network.py           # Network graph generation
│   │   ├── influence.py         # Influence network analysis
│   │   ├── relationships.py     # Email/document relationship extraction
│   │   ├── merge.py             # Investigation merging + deep-dive
│   │   ├── synthesis.py         # Report synthesis
│   │   ├── analyze.py           # Batch document analysis
│   │   ├── flights.py           # Flight data API
│   │   ├── people.py            # People database
│   │   ├── indexing.py          # ChromaDB indexing
│   │   ├── ocr.py               # OCR + image extraction
│   │   ├── settings_routes.py   # App settings
│   │   └── status.py            # System health + dashboard stats
│   │
│   ├── agents/                  # 9 AI agent modules
│   │   ├── vectordb.py          # ChromaDB ops, entity extraction, graph building
│   │   ├── investigator.py      # Person dossier generator
│   │   ├── network_agent.py     # Relationship graph mapper
│   │   ├── investigation_crew.py # 6-agent orchestrated investigation
│   │   ├── influence_analyzer.py # International org influence mapper
│   │   ├── meta_investigator.py # Cross-investigation comparator
│   │   ├── context_provider.py  # RAG + MongoDB context retrieval
│   │   └── orchestrator.py      # Agent coordination helpers
│   │
│   ├── services/                # 13 service modules
│   │   ├── claude.py            # Anthropic client + retry logic
│   │   ├── justice_gov.py       # Justice.gov search API
│   │   ├── pdf.py               # PDF download, extraction, auto-indexing
│   │   ├── emails.py            # Email dataset search (parquet)
│   │   ├── entities.py          # NER + keyword extraction
│   │   ├── people.py            # People collection CRUD
│   │   ├── documents.py         # Local document management
│   │   ├── fact_checker.py      # EFTA citation verification
│   │   ├── settings.py          # Settings cache (60s TTL)
│   │   ├── network_builder.py   # Network data construction
│   │   ├── merge_logic.py       # Investigation merge logic
│   │   └── jobs.py              # Background job management
│   │
│   ├── templates/               # 20 HTML pages (~18k lines)
│   └── static/                  # sidebar.js, sidebar.css, icon.png
│
├── chroma_db/                   # ChromaDB persistent storage
├── documents/                   # Downloaded PDFs + extracted text
├── saved_analyses/              # Exported influence analysis JSON
├── epstein_flights_data.json    # Epstein flight records
├── epstein_emails.parquet       # Email dataset
└── requirements.txt             # Python dependencies
```

**Codebase:** ~8,300 lines Python + ~18,000 lines HTML/JS

---

## Installation

### Prerequisites

- Python 3.11+
- MongoDB (running on `localhost:27017`)
- Tesseract OCR (optional, for scanned PDFs)
- Poppler (optional, for PDF-to-image conversion)
- An Anthropic API key (Claude)

### Steps

```bash
# Clone the repository
git clone https://github.com/Pinperepette/parrhesepstein.git
cd parrhesepstein

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install Python dependencies
pip install -r requirements.txt

# Install system dependencies (macOS)
brew install tesseract poppler

# Install system dependencies (Ubuntu/Debian)
# sudo apt-get install tesseract-ocr poppler-utils

# Ensure MongoDB is running
mongosh --eval "db.runCommand({ping: 1})"
```

### Data Files

The application expects two data files in the project root:

| File | Description | Source |
|------|-------------|--------|
| `epstein_flights_data.json` | Flight passenger records | Included in repo |
| `epstein_emails.parquet` | Email dataset (~4,300 emails) | [Hugging Face](https://huggingface.co/datasets) |

Both are optional. The app functions without them but the Flights and Email pages will be empty.

---

## Configuration

All configuration lives in `app/config.py`:

```python
MONGO_URI = "mongodb://localhost:27017/"
DB_EPSTEIN_NAME = "EpsteinAnalyses"       # Main database
DB_SETTINGS_NAME = "SnareSetting"          # API key storage

DOCUMENTS_DIR = "<project_root>/documents"  # Downloaded PDFs + text
CHROMA_PATH = "<project_root>/chroma_db"    # Vector database
ANALYSES_DIR = "<project_root>/saved_analyses"

VALID_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-4-5-20251001",
]

VALID_LANGUAGES = [
    "Italiano", "English", "Español",
    "Français", "Deutsch", "Português"
]
```

The Claude API key is configured through the Settings page (`/settings`) and stored in MongoDB, not in environment variables or config files.

---

## Running

```bash
python app/run.py
```

The application starts on **http://localhost:5001** with debug mode and threading enabled.

On first launch:
1. Navigate to `/settings`
2. Enter your Anthropic API key
3. Select your preferred Claude model and output language
4. Start investigating from the dashboard (`/`)

---

## Core Features

### 1. Document Search & Retrieval

**Endpoints:** `/api/search`, `/api/search-multi`, `/api/semantic-search`

Searches the U.S. DOJ Epstein Files database at `justice.gov/d9/2024-06/multimedia-search`. Supports:

- **Single query** — searches justice.gov with pagination (up to 10 pages)
- **Multi-source** — combines justice.gov + local email dataset results
- **Semantic (RAG)** — vector similarity search across all indexed documents in ChromaDB

Every search result that contains a PDF link is automatically **downloaded, text-extracted, and indexed** into ChromaDB in a background thread. The PDF extraction pipeline has triple fallback:

```
PyPDF2 (fast, text-based PDFs)
  → Tesseract OCR (scanned documents)
    → Claude Vision API (last resort)
```

Downloaded documents are persisted to `documents/` as both `.pdf` and `.txt` files.

---

### 2. Person Investigation

**Endpoint:** `POST /api/investigate`

Generates a comprehensive dossier on a single person using the `InvestigatorAgent`:

1. Searches justice.gov for all documents mentioning the person
2. Downloads and extracts full PDF text
3. Fetches Wikipedia background via `wikipediaapi`
4. Identifies connected people, financial amounts, dates, red flags
5. Generates AI analysis narrative with Claude

**Output structure:**
```json
{
  "name": "Leon Black",
  "wikipedia": { "title": "...", "summary": "...", "url": "..." },
  "documents_found": 42,
  "mentions": [{ "document": "...", "url": "...", "context": "..." }],
  "connections": ["Jeffrey Epstein", "Apollo Global"],
  "timeline": ["2012-03-15", "2013-07-22"],
  "financial": ["$158 million", "$40M+"],
  "red_flags": ["..."],
  "ai_analysis": "..."
}
```

Results are saved to the `people` collection in MongoDB and are accessible from the People page.

---

### 3. Crew Investigation (Multi-Agent)

**Endpoint:** `POST /api/investigation`

The most advanced investigation mode. Orchestrates a team of 6 specialized AI agents:

| Agent | Role |
|-------|------|
| **Director** | Plans search strategy — identifies terms, people, patterns to search |
| **Researcher** | Executes searches on justice.gov, downloads all documents |
| **Analyst** | Extracts key facts, people, connections, timeline from documents |
| **Banking Specialist** | Identifies financial transactions, wire transfers, shell companies |
| **Cipher Specialist** | Decodes patterns, aliases, codenames, indirect references |
| **Synthesizer** | Generates the final comprehensive report |

The pipeline runs sequentially: Director plans → Researcher searches → Analyst extracts → Banking analyzes → Cipher decodes → Synthesizer reports. Document analysis within each stage uses **parallel batch processing** via `ThreadPoolExecutor` for throughput.

**Continuation support:** `POST /api/investigation/<id>/continue` allows extending an existing investigation with a new objective, building on previous findings.

**Meta-investigation:** `POST /api/meta-investigation` compares multiple investigations, finds contradictions, and generates a unified verdict.

**Citation verification:** Every generated report is run through the fact-checker, which extracts all `EFTA` document codes and verifies them against ChromaDB and justice.gov. The UI shows a verification badge (green >80%, yellow >50%, red <50%).

---

### 5. Network Graph Analysis

**Endpoint:** `POST /api/network`

Builds a relationship graph from document co-occurrences:

1. Searches justice.gov for query terms
2. Extracts named entities from each document using sliding-window NER with false-positive filtering (email headers, locations, organizations, common verbs are excluded)
3. Builds a `NetworkX` graph where edges represent co-occurrence in the same document
4. Converts to `Vis.js` format for interactive frontend visualization
5. Identifies clusters (connected components) and hub nodes (highest degree)

The entity extraction handles 3-word names (e.g., "Sultan Bin Sulayem") and deduplicates partial matches.

---

### 6. Influence Network Mapping

**Endpoint:** `POST /api/influence-network`

Maps how Epstein's private network influenced international organizations:

**Target organizations:**
- WHO (World Health Organization)
- ICRC (International Committee of the Red Cross)
- World Bank
- Gates Foundation
- United Nations
- GAVI (Vaccine Alliance)
- IPI (International Peace Institute)

**Tracked intermediaries:** Jeffrey Epstein, Leon Black, Bill Gates, Boris Nikolic, Terje Rod-Larsen, Larry Summers, and others.

**Three depth levels:**
| Level | Pages/search | Max docs | Use case |
|-------|-------------|----------|----------|
| `small` | 2 | 30 | Quick scan |
| `medium` | 5 | 100 | Standard analysis |
| `full` | 10 | 300 | Comprehensive mapping |

Results include connection maps, financial flows, key documents, and exportable Markdown reports. Supports document deep-dives (`POST /api/influence-network/deep-analysis`) for drilling into specific findings.

---

### 7. Investigation Merging & Meta-Analysis

**Endpoints:** `POST /api/investigations/merge`, `POST /api/meta-investigation`

**Merge:** Combines multiple crew investigations into a unified analysis. Aggregates documents, connections, people, and timelines, then re-synthesizes a combined report.

**Deep-dive:** `POST /api/investigations/deep-dive` performs targeted analysis on a single document within the context of a merged investigation.

**Meta-investigation:** Compares investigations for contradictions, corroborations, and gaps. Three-phase workflow:
1. **Analyze** — compare all investigations
2. **Resolve** — search for documents that address contradictions
3. **Verdict** — generate unified conclusion

---

### 8. Report Synthesis

**Endpoint:** `POST /api/sintesi/generate`

Aggregates multiple influence analyses and deep-dives into a single structured report. Extracts and deduplicates:
- Key people and their roles
- Organizations and their connections
- Financial flows and amounts
- Document evidence chains
- Unified timeline

Output is a structured Markdown report stored in MongoDB.

---

### 9. Email Dataset Search

**Endpoint:** `POST /api/search-emails`

Searches the Epstein email dataset (~4,300 emails loaded from Parquet into a Pandas DataFrame). Searchable fields: `subject`, `from_address`, `to_address`, `message_html`, `other_recipients`.

Accessible via the JMail page (`/jmail`).

---

### 10. Flight Data Analysis

**Endpoints:** `GET /api/flights`, `GET /api/flights/passengers`

Serves Epstein flight records from JSON. Supports filtering by passenger name via URL parameter (`/flights?passenger=NAME`). The People page shows a flight icon for individuals found in the flight data, linking directly to their filtered flight records.

---

### 11. RAG Archive (Q&A)

**Endpoint:** `POST /api/archive/ask`

Ask natural language questions against all indexed documents. Uses ChromaDB semantic search to find relevant chunks, then sends them as context to Claude for a grounded answer. Accessible via the Archive page (`/archive`).

---

### 12. Citation Fact-Checker

**Module:** `app/services/fact_checker.py`

Runs automatically after every crew investigation report is generated. Extracts all `EFTA` document codes (regex: `EFTA\d{8,}`) and verifies each against:
1. ChromaDB (is the document indexed locally?)
2. Justice.gov search (does the document exist in the DOJ database?)

Results are stored alongside the investigation:
```json
{
  "citation_verification": {
    "total_citations": 12,
    "verified": 10,
    "unverified": 2,
    "details": [
      { "doc_id": "EFTA01234567", "status": "verified", "source": "chromadb" },
      { "doc_id": "EFTA99999999", "status": "unverified", "source": null }
    ]
  }
}
```

---

## API Reference

All long-running operations follow the **async job pattern**:

```bash
# Start a job
POST /api/<resource>
→ { "job_id": "uuid", "status": "started" }

# Poll for status
GET /api/<resource>/status/<job_id>
→ {
    "job_id": "uuid",
    "status": "pending | running | completed | error",
    "progress": "Downloading PDF 3/20...",
    "result": { ... }   // when completed
  }
```

### Endpoint Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/search` | Search justice.gov |
| `POST` | `/api/search-multi` | Combined justice.gov + email search |
| `POST` | `/api/search-emails` | Search email dataset |
| `POST` | `/api/semantic-search` | RAG search in ChromaDB |
| `POST` | `/api/download-pdf` | Download and extract PDF text |
| `GET` | `/api/documents` | List local documents |
| `GET` | `/api/documents/<id>/text` | Get document text |
| `GET` | `/api/documents/<id>/pdf` | Serve PDF file |
| `GET` | `/api/vectordb/stats` | ChromaDB statistics |
| `POST` | `/api/archive/ask` | RAG Q&A |
| `POST` | `/api/investigate` | Start person investigation |
| `GET` | `/api/investigate/status/<id>` | Poll investigation status |
| `POST` | `/api/investigation` | Start crew investigation |
| `GET` | `/api/investigation/status/<id>` | Poll crew status |
| `GET` | `/api/investigation/list` | List all investigations |
| `GET` | `/api/investigation/<id>` | Get investigation details |
| `POST` | `/api/investigation/<id>/continue` | Continue investigation |
| `POST` | `/api/meta-investigation` | Compare investigations |
| `POST` | `/api/network` | Generate network graph |
| `GET` | `/api/network/status/<id>` | Poll network status |
| `POST` | `/api/influence-network` | Start influence analysis |
| `GET` | `/api/influence-network/status/<id>` | Poll influence status |
| `POST` | `/api/influence-network/deep-analysis` | Deep-dive into document |
| `POST` | `/api/influence-network/export` | Export to Markdown |
| `GET` | `/api/relationships/emails` | Extract email relationships |
| `GET` | `/api/relationships/documents` | Extract co-occurrences |
| `POST` | `/api/investigations/merge` | Merge investigations |
| `POST` | `/api/investigations/deep-dive` | Document deep-dive |
| `POST` | `/api/sintesi/generate` | Generate synthesis report |
| `GET` | `/api/flights` | Flight data |
| `GET` | `/api/flights/passengers` | Unique passenger list |
| `GET` | `/api/people` | People database |
| `POST` | `/api/index-document` | Index document to ChromaDB |
| `POST` | `/api/vectordb/index-all-local` | Batch index all local files |
| `POST` | `/api/pdf-text` | Extract PDF text (with OCR) |
| `GET` | `/api/settings` | Get settings |
| `POST` | `/api/settings` | Update settings + API key |
| `GET` | `/api/status` | Health check |
| `GET` | `/api/dashboard/stats` | Dashboard statistics |

---

## Agent System

```
                    ┌─────────────────────┐
                    │  InvestigatorAgent   │  Single-person dossier
                    └─────────────────────┘
                    ┌─────────────────────┐
                    │   NetworkAgent       │  Relationship graph
                    └─────────────────────┘
                    ┌─────────────────────┐
                    │ InvestigationCrew    │  6-agent orchestrated team
                    │  ├─ Director         │
                    │  ├─ Researcher       │
                    │  ├─ Analyst          │
                    │  ├─ Banking          │
                    │  ├─ Cipher           │
                    │  └─ Synthesizer      │
                    └─────────────────────┘
                    ┌─────────────────────┐
                    │InfluenceAnalyzer     │  Org influence mapping
                    └─────────────────────┘
                    ┌─────────────────────┐
                    │  MetaInvestigator    │  Cross-investigation comparison
                    └─────────────────────┘
                    ┌─────────────────────┐
                    │  ContextProvider     │  RAG + MongoDB context
                    └─────────────────────┘
```

All agents use Claude via the Anthropic SDK with 3-retry logic on server errors. The model and language are configurable at runtime via `/settings`.

---

## Database Schema

### MongoDB: `EpsteinAnalyses`

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| `crew_investigations` | Multi-agent investigation results | `objective`, `strategy`, `analysis`, `report`, `citation_verification` |
| `people` | Person profiles and dossiers | `name`, `roles`, `relevance`, `dossier`, `connections`, `investigations` |
| `analyses` | Influence network analyses | `target_orgs`, `depth`, `result.connections` |
| `deep_analyses` | Document deep-dives | `doc_id`, `result.key_findings`, `result.red_flags` |
| `syntheses` | Aggregated reports | `analysis_ids`, `persons`, `organizations`, `synthesis` |
| `merged_investigations` | Merged investigation results | `investigation_ids`, `merged_report` |
| `searches` | Saved search results | `query`, `total_results`, `results_sample` |
| `app_settings` | Runtime configuration | `model`, `language` |

### MongoDB: `SnareSetting`

| Collection | Purpose |
|------------|---------|
| `api_keys` | Anthropic API key storage |

### ChromaDB

Single collection `epstein_documents` with:
- **Chunking:** 1,000 characters with 200-character overlap
- **Metadata:** `doc_id`, `title`, `url`, `chunk_index`, `source`
- **Embedding:** ChromaDB default (all-MiniLM-L6-v2)

---

## Data Pipeline

```
justice.gov search
       │
       ▼
  PDF download ──────────────────────────┐
       │                                 │
       ▼                                 ▼
  Text extraction                  Save to disk
  (PyPDF2/OCR/Vision)            documents/*.pdf
       │                         documents/*.txt
       ▼
  ChromaDB indexing
  (1000-char chunks)
       │
       ▼
  Available for:
  ├─ Semantic search (/api/semantic-search)
  ├─ RAG Q&A (/api/archive/ask)
  ├─ Agent context (crew investigations)
  └─ Fact-checking (citation verification)
```

Every search endpoint triggers background PDF downloads. Documents are automatically persisted and indexed without user intervention. The pipeline is idempotent — re-downloading an already-indexed document is a no-op.

---

## License

This project is intended for **research, journalism, and public accountability purposes**. The Epstein Files are public records released by the U.S. Department of Justice.

---

*Built with fearless speech in mind.*
