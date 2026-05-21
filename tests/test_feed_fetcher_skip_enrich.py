import logging
from pathlib import Path

from core.feed_fetcher import FeedFetcher
from core.models import AppConfig, FeedSource


def test_skip_enrich_feed_uses_full_rss_content(monkeypatch, tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "cyberchan_sample.xml"

    class FakeResponse:
        content = fixture.read_bytes()

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "core.feed_fetcher.request_with_retry",
        lambda **kwargs: FakeResponse(),
    )
    monkeypatch.setattr("core.feed_fetcher.fetched_path", lambda date_label: tmp_path / "fetched.json")

    config = AppConfig(
        issue_number=1,
        recipients=[],
        acs_sender="",
        acs_connection_string="",
        email_provider="smtp",
        sendgrid_api_key="",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_pass="",
        smtp_use_ssl=False,
        llm_endpoint="",
        llm_api_key="",
        llm_model="",
        llm_temperature=0.0,
        llm_max_tokens=1,
        llm_timeout=1,
        fetch_window_days=3650,
        fetch_max_workers=1,
        fetch_max_per_feed=2,
        arxiv_cap_per_category=10,
        fetch_fail_threshold=0.5,
        enrich_top_candidates=40,
        enrich_fetch_delay=0.0,
        enrich_fetch_timeout=1,
        enrich_max_body_chars=8000,
        cleanup_retention_days=7,
    )
    source = FeedSource(
        name="赛博禅心",
        url=f"file://{fixture}",
        category="newsletters",
        skip_enrich=True,
    )

    result = FeedFetcher(config, logging.getLogger(__name__)).fetch_all([source], "test")

    assert result.articles
    article = result.articles[0]
    assert len(article.raw_summary) > 1000
    assert article.skip_enrich is True
