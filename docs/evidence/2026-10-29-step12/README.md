# Evidence: instructor's acceptance test, step 12 (Amazon RDS), 29 Oct 2026

Deployment of `main` at commit **02c72aa** (Nimbus 0.10.0) with `scripts/nimbus-stack.yaml` in the
AWS Academy Sandbox (us-east-1). It was run as an independent check that changed nothing except using
the app and one EC2 reboot. Test clients: `QA-1029-A`, `QA-1029-B`. Account IDs, user names and
ARNs are blacked out. The full report is in [`QA-REPORT.md`](QA-REPORT.md). Screenshots are
compressed to 256 colours.

**Verdict:** steps 1–11 of the instructor's acceptance test pass end to end on Amazon RDS, and the
data survives an EC2 reboot. 29 of 30 checks passed. C7 failed: the date boxes were too narrow in an
894 px window.

## Part A: deployment

| Check | Result | Screenshots |
|---|---|---|
| A1 Stack `CREATE_COMPLETE` 02:05:11 SGT; `AppServer` SUCCESS signal | PASS | A1 |
| A2 Seven stack outputs | PASS | A2 |
| A3 RDS Available, **Publicly accessible: No**, `nimbus-db-sg` | PASS | A3, A4a |
| A4 DB group: only TCP 3306 from `nimbus-app-sg`; app group: 8501 public, 22 from 127.0.0.1/32 | PASS | A4b, A4c |
| A5 EC2 system log: `nimbus-setup: deployed commit 02c72aa from branch main` | PASS | A5 |
| A6 App sidebar: `Nimbus 0.10.0 · commit 02c72aa` | PASS | A6 |

## Part B: instructor's acceptance test, steps 1–11, on Amazon RDS

| Step | What was checked | Result | Screenshots |
|---|---|---|---|
| 1 | New Client ID `qa-1029-a` (stored as `QA-1029-A`) with a name | PASS | B1 |
| 2–3 | Apple, Microsoft found by name; comparison generated | PASS | B2, B3 |
| 4 | Share prices side by side (one rebased chart); AAPL $344.96 (+28.7%), MSFT $526.61 (−2.1%) | PASS | B4 |
| 5 | Revenue growth 6.4% / 17.8%, net margin 26.9% / 40.3%, operating margin 32.0% / 46.8%, debt-to-equity 1.34x / 0.13x; three trend charts, FY2022–2026 | PASS | B5a–c |
| 6 | Client's interests and notes entered; the view stayed on Discussion | PASS | B6a–b |
| 7 | Saved once; toast and "✓ Saved"; listed in the sidebar | PASS | B7a–b |
| 8 | History caption *mysql+pymysql at nimbus-db… · 1 client, 1 discussion, 2 company records*; found by client and reopened | PASS | B8a–c |
| 9 | Found by `msft` and by `microsoft`; `NVDA` finds nothing | PASS | B9a–c |
| 10 | Values at the time of the discussion (read from RDS) identical to steps 4–5 | PASS | B10a–b |
| 11 | EC2 reboot: server start time changed, counts unchanged, found and reopened by client and by company | PASS | B11a–e |

## Part C: re-test of earlier fixes

All passed except C7. See the full report for the details:

- C1 title visible;
- C2 one client, many discussions;
- C3 validation;
- C4 news on-topic;
- C5 SGT dates;
- C6 invalid range shows only the error;
- C8 selector follows the open discussion;
- C9 N/A for unreported items;
- C10 article dates;
- C11 retrieval times;
- C12 Markdown download.

## Defects found, and fixes in v0.10.1

| Defect | Severity | Cause | Fix |
|---|---|---|---|
| Saving from the pop-up saved the record, but the dialog stayed open with no feedback | Medium | A Streamlit dialog closes only when `st.rerun()` is called inside it | The dialog closes itself after a successful save; the toast and "✓ Saved" appear. Checked in a browser on Streamlit 1.50 and 1.66 |
| Confirmation showed "Note recorded 02:27" for a record stored at 02:26 | Low | A repeated click returned the new attempt's note | A repeated save returns the stored discussion |
| The dialog's date picker opened by itself over the error | Low | The first field gets the focus | Client's interests is now the first field |
| History date boxes cut off the last digit (C7) | Low | Four columns in a narrow window | The dates have a row of two columns (about 257 px each at 894 px) |
| A later discussion for an existing client lost the client's name | Low | The name was only taken from the "new client" fields | The name is read from the `clients` table |
| Header chip and Save button clipped in a narrow window | Low | One row with the summary text | The summary has its own line; the chip and button sit on the next row (no sideways scroll at 894 px) |
| Saved values listed AMD before NVDA | Low | Database order (by ticker) | The comparison's company order is used |
| Stack output `DatabaseName` described the old tables (found in screenshot A2) | Low | Template text not updated | It names `clients`, `discussions`, `discussion_companies` |

Known open issue, not a regression: news articles from Yahoo search have no summary (Feature 1).
