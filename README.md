# Generate-and-Send-Newsletter

**Auto-fetch AI news → AI curation & summarization → Generate newsletter email → Scheduled delivery**

[中文文档](README_CN.md)

---

This repo now ships **two pipelines** side-by-side. Pick the one that matches your needs:

| Pipeline | Entry point | Source | Best for |
|---|---|---|---|
| **Original (Nick's)** | `newsletter_git_action.py` | Single RSS feed → AI summary → SMTP | Simple daily digest from one source, fully driven by env vars / GitHub Actions |
| **Enhanced v5 (this PR)** | `generate.py` | 40+ curated feeds → 6-stage curation → multi-provider email | Weekly curated digest with full LLM scoring + responsive HTML template |

Everything from the original setup still works exactly as before. Read on for the enhanced pipeline.

---

## Enhanced Pipeline (v5) — Overview

```
┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────┐  ┌────────┐
│ Fetch   │→ │ Enrich  │→ │ Curate   │→ │ Compose │→ │ Send │→ │ Report │
│ 40+ RSS │  │ Full    │  │ LLM      │  │ HTML    │  │ ACS/ │  │ Logs + │
│ in para │  │ text +  │  │ scoring  │  │ email   │  │ SG/  │  │ TG     │
│ -llel   │  │ OG img  │  │ + tags   │  │ template│  │ SMTP │  │ notify │
└─────────┘  └─────────┘  └──────────┘  └─────────┘  └──────┘  └────────┘
```

### Key features

- **40+ RSS feeds** — Azure, AWS, GCP, NVIDIA, OpenAI / Anthropic / Google labs, AI media, analyst blogs (`feeds.yaml`)
- **Full-text enrichment** — `trafilatura`-based article extraction + Open Graph image scraping
- **LLM-powered curation** — DCSA-focused scoring rubric (`prompts/curate-v5.md`); works with any OpenAI-compatible endpoint
- **Responsive HTML template** — `templates/v7.html`; uses `dir=rtl` sidebar trick so desktop renders the sidebar on the right and mobile collapses it on top
- **Multi-provider email** — `acs` (Azure Communication Services), `sendgrid`, or `smtp`, picked from `config.yaml`
- **Production-grade stability** — per-feed error isolation, LLM retry with backoff, image fallbacks (`placehold.co`), idempotent runs
- **Optional progress notifier** — set `TG_NOTIFY_SCRIPT` to ping Telegram / Slack on milestones

---

## Quick start (enhanced pipeline)

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Copy example config and fill in your keys
cp config.example.yaml config.yaml
$EDITOR config.yaml          # set llm.api_key, email.provider, recipients, etc.

# 3. Dry-run to make sure it composes the email without sending
python3 generate.py --dry-run

# 4. Full run + send
python3 generate.py
# or
./run.sh
```

`config.yaml` is gitignored — never commit it.

### Useful flags

```bash
python3 generate.py --dry-run            # build HTML, don't send
python3 generate.py --fetch-only         # stop after fetch stage (debug feeds)
python3 generate.py --to user@example.com,user@example.com # override recipients
```

Outputs:
- `output/<date>/newsletter.html` — final HTML
- `data/fetched.json`, `data/curated.json` — pipeline artifacts
- `data/send-log.json` — delivery audit log

---

## Configuring `config.yaml`

See `config.example.yaml` for the full schema. The most important sections:

### LLM

```yaml
llm:
  endpoint: "https://api.openai.com/v1/chat/completions"
  api_key: "YOUR_OPENAI_API_KEY"        # or set env LLM_API_KEY / OPENAI_API_KEY
  model: "gpt-4o"
```

Any OpenAI-compatible Chat Completions endpoint works (OpenAI, Azure OpenAI proxy, vLLM, LiteLLM, Ollama with the OpenAI shim, Claude via `anthropic-openai`, etc.).

### Email — pick a provider

```yaml
email:
  provider: "acs"          # acs | sendgrid | smtp
  recipients:
    - "user@example.com"

  # ACS
  acs_sender: "user@example.com"
  acs_connection_string: "endpoint=https://...;accesskey=YOUR_ACCESS_KEY"

  # SendGrid (alternative)
  # sendgrid_api_key: "SG.xxxx"

  # SMTP (alternative)
  # smtp_host: "smtp.office365.com"
  # smtp_port: 587
  # smtp_user: "user@example.com"
  # smtp_pass: "..."
```

You can also pass secrets via env vars instead of `config.yaml`:
- `ACS_CONNECTION_STRING`
- `SENDGRID_API_KEY`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
- `LLM_API_KEY` / `OPENAI_API_KEY`

---

## Customizing

| What | Where |
|---|---|
| Add / remove RSS feeds | `feeds.yaml` (grouped by category) |
| Change scoring rubric / categories / tone | `prompts/curate-v5.md` |
| Change visual layout | `templates/v7.html` (table-based, email-client-safe) |
| Change LLM model / temperature / max_tokens | `config.yaml` → `llm:` |
| Change look-back window / feed concurrency | `config.yaml` → `fetch:` |

---

## Scheduling

### cron (server / VM)

```cron
# Every Monday 09:00 local time
0 9 * * 1  cd /path/to/Generate-and-Send-Newsletter && ./run.sh >> run.log 2>&1
```

### GitHub Actions

Nick's existing workflow at `.github/workflows/Generate-and-Send-Daily-AI-Newsletter.yaml` continues to run the **original** pipeline. To schedule the **enhanced** one, add a second workflow that:

1. Writes `config.yaml` from a repo secret (e.g. `NEWSLETTER_CONFIG`)
2. Runs `python generate.py`

Example fragment:

```yaml
- name: Materialize config
  run: 'echo "$NEWSLETTER_CONFIG" > config.yaml'
  env:
    NEWSLETTER_CONFIG: ${{ secrets.NEWSLETTER_CONFIG }}

- name: Generate + send
  run: python generate.py
```

---

## File layout

```
.
├── generate.py                # ★ Enhanced v5 pipeline (this PR)
├── feeds.yaml                 # ★ 40+ curated feeds
├── config.example.yaml        # ★ Copy → config.yaml
├── prompts/
│   └── curate-v5.md           # ★ DCSA scoring rubric prompt
├── templates/
│   └── v7.html                # ★ Responsive email template
├── run.sh                     # ★ Wrapper (loads .env / venv)
│
├── newsletter_git_action.py   # Original pipeline (Nick) — unchanged
├── function/                  # Original pipeline modules — unchanged
├── NewsTemplate/              # Original template — unchanged
└── .github/workflows/         # Original GitHub Actions workflow — unchanged
```

---

## Original pipeline

The original simple-RSS / SMTP pipeline is fully preserved. Its setup instructions are below for completeness.

### Quick start (original)

```bash
pip install -r requirements.txt
# Set env vars (see .env example below)
python newsletter_git_action.py
```

### Required env vars (original)

```env
AZURE_OPENAI_TOKEN=your_azure_openai_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
RSS_URL=https://your-rss-feed-url.com/rss.xml
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SENDER_USERNAME=user@example.com
SENDER_PASSWORD=your_email_password
TO_ADDRS=user@example.com,user@example.com
FROM_ALIAS=AI Newsletter
```

GitHub Actions workflow: `.github/workflows/Generate-and-Send-Daily-AI-Newsletter.yaml`.

---

## License

MIT — see `LICENSE`.

## GitHub Actions Setup

### Required Secrets

Go to repo **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value | Example |
|--------|-------|---------|
| `LLM_ENDPOINT` | Primary LLM API endpoint | `https://your-apim.azure-api.net/grok/chat/completions` |
| `LLM_API_KEY` | Primary LLM subscription key | APIM subscription key |
| `LLM_MODEL` | Primary model name | `grok-4-20-reasoning` |
| `LLM_FALLBACK_ENDPOINT` | Fallback LLM endpoint | `https://your-apim.azure-api.net/openai/deployments/gpt-54/chat/completions?api-version=2024-10-21` |
| `LLM_FALLBACK_API_KEY` | Fallback subscription key | APIM subscription key |
| `LLM_FALLBACK_MODEL` | Fallback model name | `gpt-54` |
| `ACS_CONNECTION_STRING` | Azure Communication Services connection string | `endpoint=https://...;accesskey=YOUR_ACCESS_KEY` |
| `ACS_SENDER` | ACS sender email address | `user@example.com` |
| `RECIPIENTS` | Recipient email address | `user@example.com` |

### Schedule
- Runs every **Tuesday at 09:00 HKT** (01:00 UTC)
- Can also be triggered manually from Actions tab → "Run workflow"

### Artifacts
Each run saves the generated newsletter HTML as a downloadable artifact (retained 30 days).
