# Evidence: news summaries and sources (Feature 1), local test, 29 Oct 2026

**Scope: a local test on a team laptop, not on AWS.** Nimbus 0.10.2 (commit `cabe9ba`) was run
with `python -m streamlit run src/app.py` against live Yahoo Finance data and a local SQLite
database. An independent browser check ran on 29 Oct 2026, 03:29–03:33 SGT; it used only the
app and opened article links read-only for the spot check. The AWS deployment of this version
is still to be tested.

**Why this test:** Feature 1 requires news with a **summary and a source citation**. Yahoo's news
feed currently returns no articles, and Yahoo search articles carry no summary (both shown by
`scripts/debug_news.py`). Version 0.10.2 adds summaries from Yahoo's RSS headline feed, labelled
by source and never generated (see the README, *News sources*).

**Verdict:** all 7 checks passed. Feature 1 (news with a summary and a source) works locally.

| ID | Check | Result | Observed | Screenshots |
|---|---|---|---|---|
| S1 | App version | PASS | Sidebar: *Nimbus 0.10.2 · server started 29 Oct 2026, 03:27* | S1_version_0.10.2 |
| C1 | AAPL and JPM: more than half of each company's articles have a summary; RSS summaries labelled | PASS | AAPL: 5 shown, 4 with summary (3 labelled "summary via Yahoo Finance RSS", 1 RSS-only). JPM: 5 shown, 4 with summary (2 labelled, 2 RSS-only) | C1_AAPL_JPM_news_all_1–3, C1_AAPL_only, C1_JPM_only |
| C2 | DBS (D05.SI) and OCBC (O39.SI) show articles (Yahoo search returns none for SGX tickers) | PASS | 5 articles each, all with a summary, all from the RSS feed | C2_DBS_OCBC_news_all, C2_DBS_only, C2_OCBC_only |
| C3 | No off-topic stories | PASS | All 20 articles name their company | — |
| C4 | Every card shows a source | PASS | 20 of 20 show a publisher or "via Yahoo Finance RSS (publisher not listed)" | all C1, C2 |
| C5 | Saved and reopened discussion keeps the news | PASS | Client `NEWS-TEST-1`: the same 10 DBS/OCBC articles, summaries, labels and sources after reopening | C5_saved_NEWS-TEST-1, C5_history_search, C5_reopened_news_1–2 |
| C6 | Summaries are not generated | PASS | 4 summaries compared with the source pages; all match the page description or opening text word for word | — |

Status lines shown above the articles:
- *"AAPL, JPM: Yahoo's news feed was empty, so articles come from Yahoo search, with summaries and extra articles from Yahoo's RSS feed."*
- *"D05.SI, O39.SI: Yahoo's news feed was empty, so articles come from Yahoo's RSS feed (publishers not listed)."*

## Findings (low)

- The status line describes the whole comparison, even when the company filter shows only one company. *Later fixed in the wording: the line now starts "For this comparison:" (commit after this test).*
- A story naming both DBS and OCBC appears under both companies. This is correct per company, so it shows twice in the combined list.
- The live view shows recent articles as relative times ("16d ago"); a reopened discussion shows dates. They agree.

## Limits of this evidence

- News changes hourly, so the counts describe this run only. Some articles still have no summary when
  neither Yahoo source provides one (for example, 1 of 5 for AAPL and for JPM in this run).
- Local test only: the same check is part of the final AWS regression.
