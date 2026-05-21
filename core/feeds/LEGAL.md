# Telegram channel source — legal & ToS posture

## Summary

This module is a Telegram channel adapter for the newsletter pipeline. It reads
public Telegram channel posts via Telegram's official HTML web mirror
(`https://t.me/s/<channel>`) so that the curator can include recent items from
selected channels in the human-edited digest. All content fetched by this
module is publicly accessible to any browser without authentication, without a
Telegram account, and without invoking the Bot API or the MTProto client
protocol.

## Why this is in `core/feeds/` (not the generic `core/feed_fetcher.py`)

Telegram's HTML mirror is structurally unlike RSS or Atom — it returns rendered
channel pages rather than a feed document, requires its own HTML parsing
logic, and carries Terms-of-Service considerations that do not apply to
ordinary feed sources. Isolating it in `core/feeds/` keeps the ToS-relevant
code path easy to locate, review, and disable independently of the generic
feed fetcher. A reviewer auditing the project's compliance posture can read
this file together with the adjacent adapter in a single pass, and an operator
who wants to disable the integration entirely can do so by removing the
`telegram:` section of `config/feeds.yaml` without touching any other source
or running any migration.

## Upstream terms we respect

- Read only `https://t.me/s/<channel>` — Telegram's documented public web view; no authentication, no bot API, no MTProto, no private channels.
- Cap fetches at **≤20 posts per channel per pipeline run** (configurable lower, never higher).
- Treat output as **editorial reference material**, not training data; the LLM curator summarizes for human readers and the digest is sent only to opted-in recipients.
- Preserve original attribution in the rendered newsletter — every Telegram post surfaces its channel name (`source_name`) and a clickable back-link to the canonical `https://t.me/<channel>/<post_id>` URL.
- Honor opt-out: a channel removed from `config/feeds.yaml` stops being fetched on the next run, and any cached articles for that channel expire on the standard `cleanup_retention_days` schedule.

## What we deliberately do NOT do

- We do **not** bypass Telegram's blocks, rate limits, captchas, or any anti-scraping mechanism — a non-200 response means we skip that fetch and log a warning.
- We do **not** persist raw HTML beyond the runtime of a single fetch; only structured per-post fields (title, body text, link, timestamp, image URL) are kept in `data/fetched-<date>.json`.
- We do **not** retain or republish images, videos, or files — only the URL is recorded; images are hot-linked into the rendered email at send time and not stored.
- We do **not** train, fine-tune, or evaluate any machine-learning model on Telegram content.
- We do **not** scrape private channels, supergroups, comments, replies, or member lists — only top-level posts of the public channel itself.
- We do **not** circumvent geo or IP blocks via proxies; reachability is left to the standard CI runner / operator environment.

## Reference to Telegram ToS

The relevant upstream clause is the Telegram Content Licensing terms. This
document paraphrases the restriction rather than reproducing the policy text
in full, both for brevity and to avoid republishing copyrighted policy
language:

> Telegram Terms of Service — Content Licensing: <https://telegram.org/tos/content-licensing>
>
> The clause restricts large-scale scraping of channel content for AI/ML training. This integration is not training, is small-volume, is attributed, and is editorial — the mitigations above are designed to keep it on the safe side of that line.

If Telegram updates the linked clause in a way that changes the analysis,
maintainers will revisit this document and the per-channel configuration
before the next pipeline run and record the outcome in the revision history
below.

## Configuration audit trail

Any channel added to `config/feeds.yaml` under the `telegram:` category
implicitly affirms the commitments listed above. Reviewers merging such a
change should verify that the channel is public and reachable at
`https://t.me/s/<channel>`, that the per-fetch cap remains at or below 20,
and that the pull request or linked issue records a documented internal
reason for including the channel — for example a short rationale in the PR
description, an issue link, or a brief note in the commit message.
Additions that lack that audit trail should be rejected during code review.
Removing a channel does not require the same level of justification and may
be done at any time by deleting its entry from the configuration file.

## Contact for takedown / objection

A channel operator who objects to inclusion may open a GitHub issue on the
upstream repository at
<https://github.com/Nick287/Generate-and-Send-Newsletter/issues/new>
requesting removal. Maintainers commit to removing the named channel from
`config/feeds.yaml` within one weekly digest cycle of the issue being filed
and to expiring any cached entries for that channel on the standard
retention schedule. No email contact is published for this purpose; the
GitHub issue tracker is the sole intake channel, which keeps the request,
the maintainer response, and the resulting configuration change visible
together in one public record.

## Revision history

| Date | Change |
| --- | --- |
| 2026-05-21 | Initial version. Path A posture for `t.me/s/AI_News_CN` integration. |

---

*This document is the maintainers' stated posture, not legal advice. Maintainers will update it if Telegram or Microsoft Legal provides further guidance.*
