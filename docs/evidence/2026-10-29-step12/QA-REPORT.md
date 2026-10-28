# Nimbus QA – step 12 evidence (29 Oct 2026, SGT)

Stack `nimbus`, us-east-1. App http://ec2-54-225-34-114.compute-1.amazonaws.com:8501. Browser viewport 894×567 CSS px.
AWS account ID and user name redacted in all AWS console screenshots (and Owner / Instance ARN fields).

## Results

| ID | Expected | Observed | Result | Screenshot |
|---|---|---|---|---|
| A1 | CREATE_COMPLETE; AppServer SUCCESS signal | nimbus CREATE_COMPLETE 2026-10-29 02:05:11 UTC+0800; AppServer 02:05:07 "Received SUCCESS signal with UniqueId i-0e9eea9788ef2c815" | PASS | A1_cfn_events |
| A2 | 7 outputs | NimbusUrl http://ec2-54-225-34-114.compute-1.amazonaws.com:8501; PublicIp 54.225.34.114; InstanceId i-0e9eea9788ef2c815; VpcId vpc-0a46303c55a56bd98; PrivateSubnets subnet-0cf4fb6e70804efb9,subnet-0ca4d89131bc171c5; DatabaseEndpoint nimbus-db.cdgyu2umrhtq.us-east-1.rds.amazonaws.com; DatabaseName nimbus | PASS | A2_cfn_outputs |
| A3 | Available; not public; nimbus-db-sg | Available; Publicly accessible: No; VPC SG sg-0ae3a81f1fbba3b74 (group name nimbus-DbSecurityGroup-oT2xViNTM8Zd, Name tag nimbus-db-sg) | PASS | A3_rds_connectivity, A4a_sg_list |
| A4 | db-sg: 1 rule 3306 from app-sg; app-sg: 8501 0.0.0.0/0 + 22 127.0.0.1/32 | nimbus-db-sg: 1 inbound, MYSQL/Aurora TCP 3306, source sg-0f5b13073b195b34c (= nimbus-app-sg). nimbus-app-sg: 2 inbound: TCP 22 127.0.0.1/32, TCP 8501 0.0.0.0/0 | PASS | A4b_db_sg_inbound, A4c_app_sg_inbound |
| A5 | deployed commit line | "nimbus-setup: deployed commit 02c72aa from branch main"; also "Connected to mysql+pymysql at nimbus-db…:3306. Tables ready. Row counts: {clients: 0, discussions: 0, discussion_companies: 0}" | PASS | A5_system_log_commit |
| A6 | 0.10.0 · commit 02c72aa | "Nimbus 0.10.0 · commit 02c72aa · server started 29 Oct 2026, 02:14 SGT" | PASS | A6_C1_app_sidebar_version |
| B1 | No error under ID | qa-1029-a / QA Test Client, no message | PASS | B1_client_id |
| B2 | AAPL, MSFT chips | "AAPL · Apple Inc.", "MSFT · Microsoft Corporation", both NASDAQ | PASS | B2_company_chips |
| B3 | Header + Unsaved chip | "Comparison of AAPL, MSFT · generated 29 Oct 2026, 02:15 SGT · price period 1 year", "● Unsaved discussion" | PASS | B3_generated_header |
| B4 | One rebased chart, closes and returns | Chart rebased to 100 on 28 Oct 2025; AAPL $344.96 (28.7% / 1y), MSFT $526.61 (-2.1% / 1y), as of 28 Oct 2026 | PASS | B4_price_chart |
| B5 | 4 ratio rows, 3 trend charts, years | Rev growth AAPL 6.4% / MSFT 17.8%; Net margin 26.9% / 40.3%; Op margin 32.0% / 46.8%; D/E 1.34x / 0.13x. Three trend charts; trend table 2022–2026 | PASS | B5a_financial_table, B5b_trend_charts, B5c_trend_figures |
| B6 | Client line; today; fields stay | "Client: QA-1029-A QA Test Client"; date 2026/10/29; all 3 fields kept, stayed on Discussion | PASS | B6a_C7_discussion_client_date, B6b_discussion_fields_filled |
| B7 | Saved msg, toast, ✓ Saved, buttons gone, sidebar | "This discussion snapshot was saved."; toast "Discussion with QA-1029-A saved"; "✓ Saved"; no Save buttons; sidebar "QA-1029-A · AAPL, MSFT · 29 Oct" | PASS | B7a_saved_toast_sidebar, B7b_saved_chip_banner |
| B8 | Caption 1/1/2; open by client | "Database: mysql+pymysql at nimbus-db.cdgyu2umrhtq.us-east-1.rds.amazonaws.com:3306 · 1 client, 1 discussion, 2 company records."; Historical snapshot banner + interests/notes | PASS | B8a_history_caption, B8b_search_client, B8c_C11_snapshot_banner |
| B9 | msft / microsoft found, NVDA none | msft → found and opened; microsoft → found; NVDA → "No saved discussions match these filters." | PASS | B9a_msft_open, B9b_microsoft_found, B9c_nvda_none |
| B10 | Values identical | $344.96 / $526.61, 28 Oct 2026, 6.4/17.8%, 26.9/40.3%, 32.0/46.8%, 1.34x/0.13x – identical; Comparison as saved identical | PASS | B10a_values_at_time, B10b_values_and_comparison_as_saved |
| B11 | Server restarted after reboot, data persists | Pre-reboot caption 2 clients, 3 discussions, 6 company records. Reboot initiated 02:29 SGT. At 02:31 app up: "server started 29 Oct 2026, 02:31 SGT"; caption unchanged; client QA-1029-A and company msft both reopen the AAPL/MSFT discussion with same values and notes | PASS | C3f_B11pre_counts_2clients, B11a–B11e |
| C1 | Title visible | "☁️ Nimbus" heading fully visible | PASS | C1_title_visible |
| C2 | 1 client, 2 discussions, 4 records; newest first | Caption "1 client, 2 discussions, 4 company records."; NVDA, AMD listed above AAPL, MSFT | PASS | C2a–C2d |
| C3 | Warning; error; nothing saved; clients=2 | Warning "A client ID is 1–32 letters, digits, - or _, …"; error "Please add a client (…valid Client ID…) and notes about the client's interests before saving."; counts unchanged; QA-1029-B saved → 2 clients | PASS (see defect 1) | C3a–C3e |
| C4 | NVDA/AMD articles on-topic | 5 articles: 1 NVDA ("Prediction: This Will Be Nvidia's Stock Price…"), 4 AMD (all name AMD / Advanced Micro Devices). No off-topic headline. All 5 "No summary provided by the source." (known issue) | PASS | C4_news_nvda_amd_live |
| C5 | SGT column; today finds, yesterday none | Saved (SGT) "2026-10-29 02:16"; 29→29 found; 28→28 "No saved discussions match these filters." | PASS | C5a, C5b, C5c |
| C6 | Error only | "“Discussion from” is after “Discussion to”. Swap the dates and search again." – no table/selector | PASS | C6_invalid_range_error_only |
| C7 | Full date in boxes | History date boxes show "2026/10/2" (last digit hidden behind clear ×) for both 28 and 29 Oct; Discussion-date box shows full "2026/10/29" | FAIL | C7_date_boxes_truncated |
| C8 | Selector follows | After sidebar → older AAPL/MSFT discussion, selector = "29 Oct 2026 · QA-1029-A · AAPL, MSFT" | PASS | C8_selector_follows_sidebar |
| C9 | 9 items, N/A not blank/0 | NVDA and AMD each list 9 items; NVDA Total liabilities N/A for all years | PASS | C9_financials_NA |
| C10 | SGT dates | Live "18m/51m/2h ago" → saved 29 Oct 2026; "3h ago" (≈23:2x SGT 28 Oct) → 28 Oct 2026 | PASS | C10a, C10b |
| C11 | Header and banner agree | Header "generated 02:25 SGT from data retrieved 02:21 SGT"; banner "data retrieved 29 Oct 2026, 02:21 SGT" | PASS | C11a, C11b, B8c |
| C12 | Markdown header | File content starts "# Nimbus client discussion: QA-1029-A · NVDA, AMD", then Client ID, Discussion date, Companies, Client's interests | PASS | C12_download_button |

## Defects
1. **Medium – Save dialog gives no feedback / delayed save.** Steps: New client, ID "QA 1029", generate NVDA+AMD, header 💾 Save discussion → dialog → Save with empty interests (error, correct) → change Client ID to QA-1029-B (dialog reopens) → type interests in dialog → 💾 Save discussion (3 clicks). Observed: dialog stays open, no toast, sidebar and caption unchanged ≥5 s after each click. Record was in fact stored at 02:26 SGT (file …20261028T182631Z) and only appeared after closing the dialog; one record only (2/3/6). Confirmation then said "Note recorded 02:27" vs stored 02:26. Also the date picker auto-opens on the dialog and covers the error message. Expected: immediate confirmation and dialog closes.
2. **Low – C7 regression: History date boxes truncated** ("2026/10/2") at 894 px viewport; 28 and 29 Oct indistinguishable. Expected full "2026/10/29".
3. **Low – Client name missing on later discussions:** second QA-1029-A discussion shows "Client: QA-1029-A" / "Client ID: QA-1029-A" without "QA Test Client" (first one shows it).
4. **Low – Header overflow at 894 px:** "● Unsaved discussion" chip truncated, "💾 Save discussion" clipped at right edge; page scrolls horizontally.
5. **Low – Column order:** "Values at the time of the discussion" lists AMD, NVDA while the comparison is NVDA, AMD.
6. Known open issue (not regression): all news articles show "No summary provided by the source."

## Verdict
Steps 1–11 of the instructor's acceptance test PASS end to end on Amazon RDS (commit 02c72aa, v0.10.0), including persistence across the EC2 reboot.
