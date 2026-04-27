# AI Weekly Digest

**Auto-fetch 40+ RSS feeds → LLM curation & scoring → Responsive HTML newsletter → Scheduled email delivery**

[中文文档](README_CN.md)

---

## Overview

A fully automated AI newsletter pipeline that:

1. **Fetches** 40+ RSS/Atom feeds in parallel (Azure, AWS, GCP, OpenAI, Anthropic, research labs, media …)
2. **Enriches** articles with full-text extraction + OG image scraping
3. **Curates** via LLM — scores, tags, ranks, writes summaries
4. **Composes** a responsive HTML email from a template
5. **Sends** via SMTP / Azure Communication Services / SendGrid

Two ways to run:

| Mode | Entry point | Features |
|---|---|---|
| **Plain orchestrator** | `python run_pipeline.py` | Sequential 5-step pipeline, simple & debuggable |
| **Agent Framework** | `python agent_run.py` | Per-step checkpointing, streaming, resume on failure |

---

## Project Structure

```
.
├── agent_run.py               # Agent Framework workflow entry point
├── run_pipeline.py            # Plain pipeline orchestrator
├── requirements.txt
│
├── config/
│   ├── config.yaml            # Main config (gitignored)
│   ├── config.example.yaml    # Template — copy to config.yaml
│   └── feeds.yaml             # 40+ RSS feed sources (9 categories)
│
├── core/                      # Core library
│   ├── models.py              # Dataclasses (Article, AppConfig, ...)
│   ├── paths.py               # Path constants & helpers
│   ├── constants.py           # Business constants (tags, patterns, ...)
│   ├── config_loader.py       # ConfigLoader
│   ├── llm_client.py          # LlmClient (OpenAI-compatible)
│   ├── feed_fetcher.py        # FeedFetcher
│   ├── article_enricher.py    # ArticleEnricher
│   ├── content_curator.py     # ContentCurator
│   ├── html_composer.py       # HtmlComposer
│   ├── email_dispatcher.py    # EmailDispatcher
│   └── utils/                 # Utility sub-package
│       ├── logging.py         #   Logging & Telegram notification
│       ├── text.py            #   HTML strip, truncate, escape
│       ├── dates.py           #   Date/time helpers & parsing
│       ├── articles.py        #   Dedup, save/load JSON
│       ├── http.py            #   HTTP request with retry
│       ├── images.py          #   Image URL validation
│       ├── modules.py         #   Lazy module loaders
│       └── cleanup.py         #   Old data file cleanup
│
├── steps/                     # Decoupled step functions
│   ├── step0_config.py        # Load & validate config
│   ├── step1_fetch.py         # Fetch RSS feeds
│   ├── step2_enrich.py        # Pre-score & enrich articles
│   ├── step3_curate.py        # LLM curation
│   ├── step4_compose.py       # Compose HTML newsletter
│   └── step5_send.py          # Send email
│
├── prompts/
│   └── curate-v5.md           # LLM curation prompt (scoring rubric)
├── templates/
│   └── v7.html                # Responsive HTML email template
│
├── artifacts/                 # Intermediate data (gitignored)
│   ├── fetched-YYYY-MM-DD.json
│   ├── enriched-YYYY-MM-DD.json
│   ├── curated-YYYY-MM-DD.json
│   └── send-log.json
├── dist/                      # Final output (gitignored)
│   └── newsletter-YYYY-MM-DD.html
│
├── function/                  # Legacy modules (EmailSender used by SMTP)
└── .github/workflows/
    └── Generate-and-Send-Daily-AI-Newsletter.yaml
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` — at minimum set:

```yaml
llm:
  api_key: "sk-..."           # or set env LLM_API_KEY / OPENAI_API_KEY
  model: "gpt-4o"

email:
  provider: "smtp"             # acs | sendgrid | smtp
  recipients:
    - "you@example.com"
  smtp_host: "smtp.example.com"
  smtp_port: 587
  smtp_user: "you@example.com"
  smtp_pass: "..."
```

### 3. Run

```bash
# Plain orchestrator
python run_pipeline.py --dry-run        # compose without sending
python run_pipeline.py                  # full run

# Agent Framework (with checkpointing)
python agent_run.py --dry-run
python agent_run.py
python agent_run.py --stream            # watch events in real time
```

---

## Running with Agent Framework

`agent_run.py` uses [Microsoft Agent Framework](https://pypi.org/project/agent-framework/) to model each pipeline step as an independent `Executor` node, connected via `WorkflowBuilder.add_edge()` into a directed workflow graph:

![Workflow Visualizer](image/workflow.png)

### Why a Multi-Executor Workflow?

A traditional script runs all steps inside a single function — if something fails halfway, you restart from scratch. By decomposing the pipeline into **6 independent executor nodes**, we get:

| Advantage | Description |
|---|---|
| **Visual Observability** | Each node appears in the [Microsoft Foundry Visualizer](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio) — you can watch the execution flow in real time |
| **Fault Isolation** | If Step 3 (LLM curation) fails, Steps 0–2 results are preserved; you don't re-fetch or re-enrich |
| **Checkpointing** | The framework automatically checkpoints completed nodes — resume from the last successful step on retry |
| **Streaming Events** | Built-in `executor_invoked` / `executor_completed` events let you monitor progress without custom logging |
| **Extensibility** | Add a new step (e.g., "translate", "summarize to Slack") by adding one `Executor` class and one `.add_edge()` call |
| **Production-ready** | Swap `InMemoryCheckpointStorage` → `CosmosCheckpointStorage` for durable distributed state |

### Workflow Graph

```
ConfigLoader → FeedFetcher → ArticleEnricher → StoryCurator → HtmlComposer → EmailSender
```

Each node passes a shared `PipelineState` dataclass downstream. The Visualizer shows which node is active, completed, or failed.

### Usage

```bash
# HTTP Server mode (for Agent Inspector / Visualizer)
python agent_run.py

# CLI mode
python agent_run.py --cli --dry-run        # skip email send
python agent_run.py --cli                  # full run
python agent_run.py --cli --to a@x.com     # override recipients
```

### Visualizer Setup

1. Install the [Microsoft Foundry for VS Code](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio) extension
2. Open Command Palette (`Ctrl+Shift+P`) → `Microsoft Foundry: Open Visualizer for Hosted Agents`
3. Run your agent — the graph updates in real time

---

## CLI Reference

### `run_pipeline.py`

```bash
python run_pipeline.py                      # full pipeline
python run_pipeline.py --dry-run            # skip email send
python run_pipeline.py --fetch-only         # stop after fetch + enrich
python run_pipeline.py --compose-only       # re-compose from latest curated artifact
python run_pipeline.py --to a@x.com,b@y.com # override recipients
```

### `agent_run.py`

```bash
python agent_run.py                         # full pipeline with checkpointing
python agent_run.py --dry-run               # skip email send
python agent_run.py --to a@x.com            # override recipients
python agent_run.py --stream                # stream step events
```

---

## Configuring `config.yaml`

See [`config/config.example.yaml`](config/config.example.yaml) for the full schema.

### LLM

```yaml
llm:
  endpoint: "https://api.openai.com/v1/chat/completions"
  api_key: "sk-..."
  model: "gpt-4o"
```

Any OpenAI-compatible endpoint works (OpenAI, Azure OpenAI, vLLM, LiteLLM, Ollama, etc.).

### Email — pick a provider

```yaml
email:
  provider: "smtp"              # acs | sendgrid | smtp
  recipients: ["team@co.com"]

  # SMTP
  smtp_host: "smtp.office365.com"
  smtp_port: 587
  smtp_user: "you@example.com"
  smtp_pass: "..."

  # ACS (alternative)
  # acs_sender: "DoNotReply@xxx.azurecomm.net"
  # acs_connection_string: "endpoint=https://..."

  # SendGrid (alternative)
  # sendgrid_api_key: "SG.xxxx"
```

Secrets can also be set via environment variables:
`LLM_API_KEY`, `OPENAI_API_KEY`, `ACS_CONNECTION_STRING`, `SENDGRID_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `TO_ADDRS`

---

## Customizing

| What | Where |
|---|---|
| Add / remove RSS feeds | `config/feeds.yaml` |
| Change scoring rubric / tone | `prompts/curate-v5.md` |
| Change visual layout | `templates/v7.html` |
| Change LLM model / temperature | `config/config.yaml` → `llm:` |
| Change look-back window | `config/config.yaml` → `fetch:` |

---

## GitHub Actions (Daily Automated Run)

The workflow at `.github/workflows/Generate-and-Send-Daily-AI-Newsletter.yaml` runs the pipeline daily at **UTC 08:00** and can also be triggered manually.

### Setup

1. Go to repo **Settings → Secrets and variables → Actions**
2. Add the secrets and variables listed below
3. The workflow runs `python agent_run.py` with config materialized from `NEWSLETTER_CONFIG` secret

### Required Secrets

| Secret | Description |
|---|---|
| `NEWSLETTER_CONFIG` | Full `config/config.yaml` content |
| `LLM_API_KEY` | LLM API key (overrides config) |

### Optional Variables (for env-var based config)

| Variable | Description |
|---|---|
| `SMTP_HOST` | SMTP server (e.g. `smtp.office365.com`) |
| `SMTP_PORT` | SMTP port (e.g. `587`) |
| `SMTP_USER` | Sender email |
| `SMTP_PASS` | SMTP password |
| `TO_ADDRS` | Recipients (comma-separated) |
| `FROM_ALIAS` | Sender display name |

---

## License

MIT — see [LICENSE](LICENSE).
