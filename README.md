# Generate-and-Send-Newsletter

**Auto-fetch AI news → AI summarize & translate → Generate newsletter email → Scheduled delivery**

[中文文档](README_CN.md)

---

## Introduction

A fully automated AI newsletter generation and delivery system. It fetches the latest AI news from an RSS feed, uses Azure OpenAI to summarize and translate the content into Chinese, generates a beautifully styled HTML email, and sends it to subscribers via SMTP. The entire pipeline runs daily via GitHub Actions.

## Workflow

```
RSS Feed → Parse Content → AI Ad Removal → AI Summary → AI Translate → HTML Email → SMTP Send
```

## Project Structure

```
├── newsletter_git_action.py        # Main entry script
├── requirements.txt                # Python dependencies
├── function/
│   ├── AzureAIClient.py            # Azure OpenAI client wrapper
│   ├── EmailSender.py              # SMTP email sender with retry
│   └── NewsCollector.py            # News collection, summary & translation
├── NewsTemplate/
│   └── AINewsTemplate.py           # HTML newsletter template
└── .github/workflows/
    └── PLAYPRO-Generate-and-Send-Daily-AI-Newsletter.yaml  # Scheduled workflow
```

## Key Features

- **RSS News Fetching** — Fetch latest AI news from a specified RSS feed
- **AI Ad Removal** — Intelligently identify and remove promotional content using LLM
- **AI Summarization** — Compress long articles into concise key points
- **AI Translation** — Auto-translate to Chinese, preserving Markdown formatting and links
- **Styled HTML Email** — Dark-themed responsive email template
- **Auto Retry** — Automatic retry on SMTP send failures
- **Scheduled via GitHub Actions** — Runs automatically at UTC 8:00 daily

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create a `.env` file for local development:

```env
# Azure OpenAI
AZURE_OPENAI_TOKEN=your_azure_openai_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/

# RSS Feed
RSS_URL=https://your-rss-feed-url.com/rss.xml

# SMTP Email Configuration
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SENDER_USERNAME=your_email@example.com
SENDER_PASSWORD=your_email_password
TO_ADDRS=recipient1@example.com,recipient2@example.com
FROM_ALIAS=AI Newsletter
```

### 3. Run Locally

```bash
python newsletter_git_action.py
```

## GitHub Actions Deployment

Add the following secrets in your repo's **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `AZURE_OPENAI_TOKEN` | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `RSS_URL` | RSS feed URL |
| `SMTP_HOST` | SMTP server host |
| `SMTP_PORT` | SMTP port (e.g. 465) |
| `SENDER_USERNAME` | Sender email address |
| `SENDER_PASSWORD` | Sender email password |
| `TO_ADDRS` | Recipients (comma-separated) |
| `FROM_ALIAS` | Sender display name |

Once configured, the workflow runs automatically at UTC 8:00 daily. You can also trigger it manually from the Actions tab.

## Tech Stack

- **Python 3.11+**
- **Azure OpenAI** — GPT for summarization, translation & ad removal
- **html2text** — HTML to Markdown conversion
- **markdown** — Markdown to HTML for email rendering
- **GitHub Actions** — Scheduled automation

## License

See [LICENSE](LICENSE) for details.