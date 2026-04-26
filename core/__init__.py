"""
AI Weekly Digest — Refactored Pipeline Package
AI 周刊摘要 — 重构后的流水线包

Each stage of the newsletter generation pipeline is encapsulated in its own class:
每个新闻简报生成流水线的阶段都封装在独立的类中：

- ConfigLoader    : Load & validate config.yaml / feeds.yaml | 加载并校验配置文件
- FeedFetcher     : Parallel RSS fetching, filtering & dedup  | 并行抓取RSS源、过滤与去重
- LlmClient       : LLM API calls with retry & fallback       | LLM API调用（含重试和降级）
- ArticleEnricher : Pre-score articles & enrich full text      | 文章预评分与全文提取
- ContentCurator  : LLM-based story curation & ranking         | 基于LLM的内容策展与排序
- HtmlComposer    : Render HTML newsletter from template       | 使用模板渲染HTML新闻简报
- EmailDispatcher : Send via ACS / SendGrid / SMTP             | 通过ACS/SendGrid/SMTP发送邮件
"""

# 数据模型导入 | Data model imports
from core.models import Article, FeedSource, AppConfig, FetchResult, StageOutcome

# 路径与常量导入 | Path & constant imports
from core.paths import (  # noqa: F401
    ROOT, CONFIG_DIR, PROMPTS_DIR, DATA_DIR, OUTPUT_DIR,
    FEEDS_FILE, CONFIG_FILE, TEMPLATES_DIR, CURATE_PROMPT_FILE,
    TMP_HTML_FILE, ACS_SECRET_FILE,
    DEFAULT_LLM_ENDPOINT, DEFAULT_LLM_MODEL, DEFAULT_ACS_SENDER,
    fetched_path, enriched_path, curated_path, output_html_path,
    ensure_directories,
)
from core.constants import (  # noqa: F401
    BAD_IMAGE_PATTERNS, SEMVER_PATTERN, IMAGE_EXTENSIONS,
    VALID_TAGS, TAG_PLACEHOLDER_COLORS,
)

# 各阶段类导入 | Stage class imports
from core.config_loader import ConfigLoader
from core.feed_fetcher import FeedFetcher
from core.article_enricher import ArticleEnricher
from core.llm_client import LlmClient
from core.content_curator import ContentCurator
from core.html_composer import HtmlComposer
from core.email_dispatcher import EmailDispatcher
