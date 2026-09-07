# DevGrow AI Evaluator

**DevGrow AI Evaluator** is an automated code review and evaluation engine built with **Django REST Framework (DRF)**, **Tree-sitter AST parsing**, and **Large Language Models (LLMs)**. It analyzes code changes between Git commits against defined acceptance criteria and computes a structured, rubric-based evaluation score.

---

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [End-to-End Evaluation Flow](#end-to-end-evaluation-flow)
- [Modules & Directory Structure](#modules--directory-structure)
- [Scoring Rubric & Criteria](#scoring-rubric--criteria)
- [API Reference](#api-reference)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Getting Started & Installation](#getting-started--installation)
- [Troubleshooting & Best Practices](#troubleshooting--best-practices)

---

## Architecture Overview

DevGrow AI Evaluator transitions code evaluation from naive diff inspection into a structure-aware, multi-phase review pipeline:

```
                  ┌─────────────────────────────────────┐
                  │ POST /api/evaluate/ (JSON Request)  │
                  └──────────────────┬──────────────────┘
                                     │
                        (DRF Serializer & Pydantic)
                                     │
                                     ▼
         ┌────────────────────────────────────────────────────────┐
         │              Evaluation Service Pipeline               │
         ├────────────────────────────────────────────────────────┤
         │ 1. Acceptance Criteria Normalization                   │
         │ 2. Git Diff Analysis & Sensitive File Filtering        │
         │ 3. Tree-sitter AST Parsing & Context Extraction        │
         │ 4. Structure-Aware Code Chunking                       │
         │ 5. Chunk-level LLM Evaluation (Tagged Findings)        │
         │ 6. Findings Consolidation, Deduplication & Grouping    │
         │ 7. Final Rubric Scoring LLM Pass                       │
         │ 8. Nested Rubric Assembly & Score Aggregation          │
         │ 9. Persist & Respond                                   │
         └───────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ 200 OK (Evaluation Response JSON)   │
                  └─────────────────────────────────────┘
```

---

## End-to-End Evaluation Flow

### Step 1: Request Ingestion & Criteria Normalization
- The API endpoint receives project metadata, task details, acceptance criteria, repository path, base commit, and target commit.
- `normalize_acceptance_criteria()` converts raw text (newlines, bullet points, numbers `1.`, `1)`, or semicolons) into a clean, uniform list of criteria.

### Step 2: Git Diff Extraction & Filtering
- `GitService` checks out the target branch (if provided) and verifies the repository.
- Resolves commit hashes (`rev-parse`) and runs `git diff --name-status` to identify added, modified, renamed, and deleted files.
- Excludes sensitive files, binary assets, and package locks (`.env`, `.pem`, `package-lock.json`, `.sqlite`, `node_modules/`, etc.) using regex patterns.
- Runs `git diff --unified=0` per file to extract exact line ranges of added and deleted lines.

### Step 3: AST Parsing & Context Extraction
- `parse_changed_code()` analyzes the code corresponding to the changed line ranges:
  - **New files**: Extracted completely.
  - **Modified files**: Tree-sitter parses the file syntax tree and locates enclosing definitions (functions, methods, classes, constructors) that overlap with the changed lines.
  - **Fallback**: Regex matching or context-padded raw line extraction if Tree-sitter parser is not available for that language.

### Step 4: Structure-Aware Chunking
- `create_chunks()` groups the extracted code fragments into chunks bounded by `CHUNK_SIZE_LIMIT` (default: 6,000 characters).
- Preserves function and class boundaries so the LLM receives complete, readable semantic blocks rather than arbitrary line slices.

### Step 5: Per-Chunk LLM Analysis
- Each chunk is reviewed independently by the LLM using a strict system prompt.
- The LLM acts as a Senior Code Reviewer, identifying **strengths**, **issues**, and **evidence** (code quotes).
- Every strength and issue is **tagged** with a metric label (e.g. `[Requirement Coverage]`, `[Code Correctness]`) so findings can be attributed to the correct scoring dimension.
- No scores are assigned at this stage, preventing partial-view score skew.

### Step 6: Deduplication, Consolidation & Grouping
- `_deduplicate()` consolidates chunk findings across all chunks using keyword set intersection to remove redundant issues and strengths.
- `_group_findings_by_metric()` routes each tagged finding into per-metric buckets and strips the tag prefix from the stored string.

### Step 7: Final Rubric Scoring
- `_final_scoring()` sends the consolidated findings, project context, and acceptance criteria to the LLM.
- The prompt includes **descriptions** for each metric so the LLM understands what each dimension measures.
- The LLM is instructed to **group findings by their metric tag** and score each metric independently based on its own subset of findings.
- The LLM scores the code across all active metrics (2 defaults + up to 3 custom).

### Step 8: Nested Rubric Assembly & Score Aggregation
- For each metric, the system assembles a nested rubric entry containing the LLM score and the grouped strengths/issues for that metric.
- The final score is computed deterministically:
  $$\text{Final Score} = \text{round}\left(\frac{\sum \text{metric scores}}{\text{metric count} \times 100} \times 100\right)$$

### Step 9: Persist & Respond
- Successful evaluations are cached in the database (keyed by repository + commits + task title).
- Returns the complete result with nested rubric.

---

## Modules & Directory Structure

```
d:/devgrow_ai_evaluator/
├── devgrow_ai_evaluator/          # Django Project Root
│   ├── __init__.py
│   ├── asgi.py                    # ASGI server entry point
│   ├── settings.py                # Django core settings & DRF configuration
│   ├── urls.py                    # Root URL router
│   └── wsgi.py                    # WSGI server entry point
│
├── evaluator/                     # Evaluator Django App
│   ├── __init__.py
│   ├── config.py                  # Environment variable loader & constants
│   ├── models.py                  # Django models (EvaluationResult, ScoringMetric)
│   ├── schemas.py                 # Pydantic models for request/response/LLM data
│   ├── serializers.py             # Django REST Framework serializers
│   ├── urls.py                    # App URL router (/api/evaluate/, /api/scoring-metrics/)
│   ├── views.py                   # API view controllers
│   └── services/                  # Business logic & domain services
│       ├── __init__.py
│       ├── acceptance_criteria.py # Criteria text cleaner & list normalizer
│       ├── chunker_service.py     # Structural chunking & line splitters
│       ├── evaluation_service.py  # Central orchestration pipeline
│       ├── git_service.py         # Subprocess Git interface & diff analyzer
│       ├── llm_service.py         # LangChain Ollama caller, Langfuse & retries
│       ├── metrics_service.py     # Aggregated performance metrics & statistics
│       └── parser_service.py      # Tree-sitter AST & regex code extractor
│
├── .env.example                   # Example environment configuration
├── manage.py                      # Django management script
└── requirements.txt               # Python package dependencies
```

### Module Descriptions

| File / Module | Responsibility |
| :--- | :--- |
| `devgrow_ai_evaluator/settings.py` | Configures Django apps, middleware, databases, and DRF settings. |
| `evaluator/config.py` | Loads `.env` file; defines LLM parameters, Langfuse keys, chunk sizes, and sensitive file regexes. |
| `evaluator/models.py` | Defines `EvaluationResult` (cached evaluation) and `ScoringMetric` (custom metrics with descriptions). |
| `evaluator/schemas.py` | Defines Pydantic validation schemas: `EvaluationRequest`, `ParsedCodeFragment`, `ChunkEvaluationResult`, `RubricScore`, and `EvaluationResponse`. |
| `evaluator/serializers.py` | Serializes and validates HTTP JSON payloads using Django REST Framework serializers. |
| `evaluator/views.py` | Entry points: `evaluate_code` (`POST /api/evaluate/`) and `update_scoring_metrics` (`POST /api/scoring-metrics/`). |
| `evaluator/services/acceptance_criteria.py` | Parses free-form user criteria strings into clean lists. |
| `evaluator/services/git_service.py` | Runs Git commands to validate repositories, switch branches, resolve commits, and extract changed line ranges. |
| `evaluator/services/parser_service.py` | Uses Tree-sitter parsers to extract AST nodes for changed lines across 20+ programming languages. |
| `evaluator/services/chunker_service.py` | Packs fragments into size-limited chunks with file and class header annotations. |
| `evaluator/services/llm_service.py` | Wraps LangChain `ChatOllama` with Tenacity exponential retry logic, Langfuse tracing, and JSON output parsing. |
| `evaluator/services/evaluation_service.py` | Coordinates the end-to-end evaluation pipeline and executes the two-phase LLM analysis with per-metric findings grouping. |

---

## Scoring Rubric & Criteria

The evaluation uses **dynamic scoring metrics**. Two metrics are always present (defaults), and up to 3 additional custom metrics can be configured via the API, for a maximum of 5 total.

### Default Metrics

| Metric | Description |
| :--- | :--- |
| **Requirement Coverage** | Percentage of acceptance criteria addressed by the code. Score based on how many criteria have a visible implementation. |
| **Code Correctness** | Whether the implemented logic is correct, free of bugs, and handles edge cases. Deduct for logic errors, crashes, or wrong outputs. |

### Custom Metrics (Examples)

| Metric | Description |
| :--- | :--- |
| **Code Quality** | Readability, naming conventions, and structural organization. |
| **Test Coverage** | Presence and quality of unit/integration tests. |
| **Performance** | Efficiency of algorithms and resource usage. |

Each metric is scored **0–100** independently. The final score is computed as:

$$\text{Final Score} = \text{round}\left(\frac{\sum \text{metric scores}}{\text{metric count} \times 100} \times 100\right)$$

### Status Thresholds
- **Met**: Requirement Coverage ≥ 30
- **Partially Met**: Requirement Coverage between 15 and 29
- **Not Met**: Requirement Coverage < 15

---

## API Reference

### Evaluate Code
`POST /api/evaluate/`

#### Request Payload
```json
{
  "project_title": "E-Commerce Backend",
  "project_description": "Django REST API for product catalog and checkout",
  "task_title": "Implement Discount Coupon Application",
  "task_description": "Add coupon validation and discount calculation on checkout",
  "acceptance_criteria": "1. Validate coupon code expiry.\n2. Apply percentage discount to total.\n3. Return error for invalid coupons.",
  "repository_path": "/path/to/local/git/repo",
  "base_commit": "main",
  "target_commit": "feature/coupon-discounts",
  "branch": "feature/coupon-discounts",
  "difficulty": "MEDIUM"
}
```

#### Successful Response (`200 OK`)
```json
{
  "score": 88,
  "status": "Met",
  "summary": "Coupon validation and percentage discount logic correctly implemented with proper error handling.",
  "rubric": {
    "requirement_coverage": {
      "score": 85,
      "strengths": [
        "Implements all three acceptance criteria: expiry validation, percentage discount, and invalid coupon error handling."
      ],
      "issues": [
        "Edge case: expired coupon with future start date not explicitly handled."
      ]
    },
    "correctness": {
      "score": 90,
      "strengths": [
        "Clean validation helper implemented with timezone-aware datetime checks.",
        "Comprehensive error responses with appropriate HTTP status codes."
      ],
      "issues": [
        "Zero percent discount coupon causes division by zero in price calculation formula."
      ]
    }
  }
}
```

#### Error Responses
- **400 Bad Request**: Invalid JSON or missing required fields.
- **500 Internal Server Error**: Git failure, parser crash, or unreachable LLM backend.

---

### Update Scoring Metrics
`POST /api/scoring-metrics/`

Manages additional scoring metrics beyond the defaults (`requirement_coverage` and `correctness` are always present). Maximum **3 additional metrics** accepted (5 total with defaults).

#### Request Payload
```json
{
  "metrics": [
    {
      "name": "code_quality",
      "display_name": "Code Quality",
      "description": "Readability, naming conventions, and structural organization. Deduct for deeply nested logic or unclear variable names."
    },
    {
      "name": "test_coverage",
      "display_name": "Test Coverage",
      "description": "Presence and quality of unit and integration tests. Score based on whether critical paths are tested."
    },
    {
      "name": "performance",
      "display_name": "Performance",
      "description": "Efficiency of algorithms and resource usage. Deduct for unnecessary loops, redundant queries, or memory leaks."
    }
  ]
}
```

#### Successful Response (`200 OK`)
```json
{
  "metrics": [
    {
      "name": "requirement_coverage",
      "display_name": "Requirement Coverage",
      "description": "Percentage of acceptance criteria addressed by the code. Score based on how many criteria have a visible implementation."
    },
    {
      "name": "correctness",
      "display_name": "Code Correctness",
      "description": "Whether the implemented logic is correct, free of bugs, and handles edge cases. Deduct for logic errors, crashes, or wrong outputs."
    },
    {
      "name": "code_quality",
      "display_name": "Code Quality",
      "description": "Readability, naming conventions, and structural organization. Deduct for deeply nested logic or unclear variable names."
    },
    {
      "name": "test_coverage",
      "display_name": "Test Coverage",
      "description": "Presence and quality of unit and integration tests. Score based on whether critical paths are tested."
    },
    {
      "name": "performance",
      "display_name": "Performance",
      "description": "Efficiency of algorithms and resource usage. Deduct for unnecessary loops, redundant queries, or memory leaks."
    }
  ]
}
```

#### Notes
- Reserved names (`requirement_coverage`, `correctness`) are silently filtered from the request — you cannot override defaults.
- Each call **replaces all** existing custom metrics atomically.
- If more than 3 custom metrics are sent, only the first 3 are saved and a `warning` field is included in the response.
- The `description` field is optional but **strongly recommended** — it is passed to the LLM so it knows what each metric should evaluate.

---

## Configuration & Environment Variables

Create a `.env` file in the project root:

```env
# LLM Configuration
LLM_MODEL=gpt-oss:20b
LLM_BASE_URL=http://172.20.201.87:9007/
LLM_API_KEY=ollama
LLM_TEMPERATURE=0.0

# Langfuse Observability & Tracing (Optional)
LANGFUSE_HOST=http://172.20.200.201:7000
LANGFUSE_PUBLIC_KEY=pk-lf-d4662c49-0e1e-4d1f-9237-187cd05e2944
LANGFUSE_SECRET_KEY=sk-lf-c4ecbe19-9df7-465f-9f10-0f0ec863b934

# Evaluation & Chunking Limits
CHUNK_SIZE_LIMIT=6000
CHUNK_OVERLAP=500
```

---

## Getting Started & Installation

### 1. Prerequisites
- **Python 3.10+**
- **Git** (installed and added to system `PATH`)
- Accessible **Ollama** or OpenAI-compatible LLM endpoint

### 2. Virtual Environment Setup
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activate virtual environment (Linux/macOS)
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
```bash
cp .env.example .env
# Edit .env with your LLM endpoint and keys
```

### 5. Run Migrations & Verify
```bash
python manage.py check
python manage.py makemigrations evaluator
python manage.py migrate
```

### 6. Start Development Server
```bash
python manage.py runserver 0.0.0.0:8000
```

---

## Troubleshooting & Best Practices

1. **Git Repository Path Errors**: Ensure `repository_path` is an absolute path accessible on the host filesystem where the Django server is running.
2. **Commit Resolution**: Ensure `base_commit` and `target_commit` exist in the target repository's Git history.
3. **Tree-sitter Language Support**: The `tree-sitter-language-pack` handles Python, JavaScript, TypeScript, Java, Go, C++, Rust, PHP, and more. If a language is unsupported, the evaluator automatically falls back to regex or line-range extraction.
4. **Custom Metrics**: Use the `/api/scoring-metrics/` endpoint to add evaluation dimensions beyond the defaults. Always include a `description` so the LLM can score each metric distinctly.
