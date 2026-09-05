# Autonomous Outreach & Research Swarm

An agentic multi-agent research & outreach swarm built with **LangGraph**, **Google Gemini 3 Pro**, **FastAPI**, **Apollo API**, and **Tavily Web Search**.

The system dynamically analyzes query intent, executes parallel web research, enriches verified target decision-maker contacts via Apollo API, synthesizes executive prose reports, and manages Human-in-the-Loop (HITL) candidate outreach.

---

## Highlights

- **Dual-Mode Dynamic Workflow Routing**: Automatically distinguishes between *General Technical/Market Research* (terminating at report synthesis) and *Sales Outreach* (enabling contact enrichment & draft approval).
- **Parallel Swarm Fan-Out**: Dynamic `Send()` dispatch spawns parallel researcher agents for multi-angle web research.
- **Verified Contact Discovery (Apollo API)**: Enriches decision makers with verified email addresses and executive titles. Strictly returns `N/A` for unverified contacts (no pattern generation).
- **State Machine & SQLite Persistence**: Built on LangGraph `SqliteSaver` checkpointer (`state.db`), enabling pause, resume, and crash recovery.
- **Executive Prose Report Synthesis**: Generates clean, non-duplicative markdown reports structured into executive narrative paragraphs with clear headings.
- **Real-Time Telemetry (SSE)**: Streams agent thinking, web search queries, scrapers, and node transitions via Server-Sent Events (`GET /jobs/{job_id}/stream`).
- **Automated Evaluation Suite (`evals/`)**: Includes LLM-as-a-Judge evaluation metrics (Answer Relevance, Fact Faithfulness, Apollo Precision) with rate-limit pacing.

---

## 🏗️ 1. High-Level Architecture (HLD)

```
                            ┌──────────────────────────────────┐
                            │    Client / Swagger UI / REST    │
                            └────────────────┬─────────────────┘
                                             │ HTTP REST / SSE Stream
                                             ▼
                            ┌──────────────────────────────────┐
                            │        FastAPI API Server        │
                            │           (main.py)              │
                            └────────────────┬─────────────────┘
                                             │ LangGraph Execution
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                            LangGraph Agent Swarm State Machine                              │
│                                                                                             │
│  [Sanitize] ──► [Guardrail] ──► [Planner] ──► [Parallel Researcher Nodes] (x5)              │
│                                                       │                                     │
│                                                       ▼                                     │
│                                              [Reranker Node]                                │
│                                                       │                                     │
│                                                       ▼                                     │
│                                           [Verifier / Apollo API]                           │
│                                                       │                                     │
│                                                       ▼                                     │
│                                              [Synthesizer Node]                             │
│                                                       │                                     │
│                           ┌───────────────────────────┴───────────────────────────┐         │
│                           │ (General Research)           (Sales Outreach)        │         │
│                           ▼                                                      ▼         │
│                        [ END ]                                         [Outreach Drafter]   │
│                                                                                  │          │
│                                                                                  ▼          │
│                                                                             [HITL Wait]     │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                             │ Checkpoint & Telemetry
                            ┌────────────────┴─────────────────┐
                            ▼                                  ▼
                 ┌────────────────────┐             ┌────────────────────┐
                 │ SQLite Checkpointer│             │  JobEventManager   │
                 │     (state.db)     │             │    (SSE Stream)    │
                 └────────────────────┘             └────────────────────┘
```

### Dynamic Routing Logic
```
                      ┌───────────────────────────────┐
                      │    Planner Node Intent Check  │
                      └───────────────┬───────────────┘
                                      │
              ┌───────────────────────┴───────────────────────┐
              │                                               │
    is_sales_outreach = False                       is_sales_outreach = True
              │                                               │
              ▼                                               ▼
   General Research Track                         Sales Outreach Track
   - Parallel Web Search                          - Parallel Web Search
   - Fact Reranking & Synthesis                   - Fact Reranking & Verification
   - Saves Markdown Report to Disk                - Apollo API Contact Enrichment
   - Exit at END                                  - Outreach Email Drafting
                                                  - Interrupt at HITL Approval
```

---

## 2. Low-Level Design (LLD)

### Module Breakdown

| Module | File | Role & Design |
| :--- | :--- | :--- |
| **API Entrypoint** | `main.py` | FastAPI application exposing REST endpoints, SSE streams, and SQLite checkpointer. |
| **Graph Definition** | `graph.py` | Compiles `StateGraph`, dynamic fan-out edges (`Send`), and conditional exit edges (`route_after_synthesizer`). |
| **Swarm State** | `state.py` | Global `State` model backed by Pydantic and annotated reducers (`operator.add`). |
| **LLM Clients** | `llm_clients.py` | 3-tier Gemini client wrapper (`cheap_llm`, `mid_llm`, `strong_llm`) with exponential backoff for rate limits. |
| **Tools & APIs** | `tools.py` | Web search (Tavily), Web Scraper (Tavily Extract / BeautifulSoup), Contact Lookup (Apollo API). |
| **Telemetry Manager**| `events.py` | In-memory thread-safe `asyncio.Queue` event manager for real-time SSE telemetry logging. |
| **Swarm Nodes** | `nodes/` | Specialized node functions (`planner`, `researcher`, `verifier`, `synthesizer`, `outreach_drafter`, `hitl`). |
| **Evaluation Suite**| `evals/` | Benchmark dataset, LLM-as-a-Judge metrics, and rate-limit safe CLI evaluation runner. |

### Data Flow & Reducers (`state.py`)
```python
class State(BaseModel):
    job_id: str
    raw_query: str
    query: str
    goal: str | None
    is_sales_outreach: bool = True
    angles: list[str] = Field(default_factory=list)
    findings: Annotated[list[Finding], operator.add]   # Fan-out reducer
    contacts: Annotated[list[Contact], operator.add]   # Fan-out reducer
    reranked: list[Finding] = Field(default_factory=list)
    report: Report | None = None
    drafts: dict = Field(default_factory=dict)
    hitl_approved: bool | None = None
```

---

## 3. Automated Evaluation Suite (`evals/`)

The repository includes a dedicated benchmark evaluation suite located in the `evals/` folder:

- **`evals/eval_dataset.json`**: Benchmark research query dataset.
- **`evals/metrics.py`**: Evaluation metrics:
  - **Answer Relevance**: LLM-as-a-Judge metric scoring report responsiveness to user query (0.0 – 1.0).
  - **Fact Faithfulness**: Evaluates factual grounding against retrieved web findings.
  - **Apollo Contact Precision**: Measures verified contact email ratio.
- **`evals/run_evals.py`**: CLI evaluation runner configured with **6-second delay pacing** (`time.sleep(6.0)`) between runs to adhere to Gemini Free Tier (15 RPM) rate limits.
- **`evals/test_eval_metrics.py`**: Unit test suite for evaluation metrics.

### Run Evaluation Unit Tests
```bash
python evals/test_eval_metrics.py
```

---

## 📑 4. Sample Executive Research Report

A representative executive prose report generated by the swarm is available in the repository:
👉 [reports/sample_executive_report.md](reports/sample_executive_report.md)

---

## ⚡ 5. API Endpoints (Swagger UI)



| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/jobs` | **1. Trigger Autonomous Research Job** (Spawns research swarm) |
| `GET` | `/jobs/{job_id}/stream` | **2. Live SSE Telemetry Log Stream** (Real-time agent thoughts & tool logs) |
| `GET` | `/jobs/{job_id}` | **3. Get Job Results & Executive Report** (Polls job state & reports) |
| `GET` | `/jobs/{job_id}/report/download` | **4. Download Research Report File (.md)** (Downloads markdown file) |
| `POST` | `/jobs/{job_id}/approve` | **5. Approve or Discard Email Draft** (HITL human approval endpoint) |

---

## 6. Quickstart & Setup

### 1. Prerequisites
- Python 3.10+
- Gemini API Key (`GEMINI_API_KEY`)
- Tavily Search API Key (`TAVILY_API_KEY`)
- Apollo API Key (`APOLLO_API_KEY`) *(optional)*

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill in your API credentials:
```bash
cp .env.example .env
```

### 3. Installation
```bash
pip install -r requirements.txt
```

### 4. Running the API Server
```bash
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` in your browser to interact with the API via Swagger UI.

---

## Security & Privacy
- Sensitive credentials (`.env`, `credentials.json`, `token.json`, `state.db`) are strictly excluded via `.gitignore`.
- Contact email enrichment relies strictly on verified API responses from Apollo API; unverified lookups output `N/A`.
