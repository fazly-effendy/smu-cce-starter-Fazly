# Nimbus v0.11.0: AWS deployment QA report (Feature 6: automatic scaling)

## 1. Header

| Item | Value |
|---|---|
| Date | Saturday 31 Oct 2026. Testing ran 13:15–14:28 SGT (section D: 14:20–14:28). |
| Tester | Independent QA (Claude, run on behalf of Fazly) |
| Guide followed | `docs/aws-deployment.md` at `ff18611`, "Evidence to capture", sections A–D |
| Version and commit in the app | Sidebar shows `Nimbus 0.11.0 · commit ff18611 · server ip-10-0-2-73 · server started 31 Oct 2026, 13:28 SGT` |
| Commit in the system log | `nimbus-setup: deployed commit ff18611 from branch main (requested commit: latest)`. **The requested commit is not ff18611; see A3 and D-1.** |
| Stack `nimbus` | Started 13:01:39 SGT ("User Initiated"). CREATE_COMPLETE at 13:09:57 SGT (8 min 18 s). |
| Load-test method | AWS CloudShell (us-east-1): 20 parallel `curl` loops for 600 s, HTTP GET to `NimbusUrl/` only. Started 13:43:57 SGT; traffic stopped at about 13:54 (CloudWatch). |
| Browser | Google Chrome with the Claude in Chrome extension. The console shows times as UTC+08:00. Alarm and activity timestamps given in UTC (Z) were converted to SGT (+8 h). |
| Region / account | us-east-1, AWS Academy Sandbox. The account ID, user names and ARNs are blacked out in every screenshot. |
| NimbusUrl | `http://nimbus-alb-364314430.us-east-1.elb.amazonaws.com` |

## 2. Results

| ID | Check | Expected | Actual | Result | Time (SGT) | Screenshots |
|---|---|---|---|---|---|---|
| A1 | Stack events | NimbusDatabase CREATE_COMPLETE; AppAutoScalingGroup "Received SUCCESS signal with UniqueId i-…"; stack CREATE_COMPLETE | NimbusDatabase: CREATE_IN_PROGRESS at 13:02:26, CREATE_COMPLETE at 13:08:06. AppAutoScalingGroup creation started 13:08:10; "Received SUCCESS signal with UniqueId i-0f4e3fa3108bbae42" at 13:09:47; CREATE_COMPLETE at 13:09:47. Stack CREATE_COMPLETE at 13:09:57. 88 events, no FAILED. | PASS | 13:16–13:17 | A1_events_nimbusdatabase_complete.png, A1_events_asg_success_signal.png, A1_events_stack_create_complete.png |
| A2 | Stack outputs | NimbusUrl, AutoScalingGroup, TargetGroup, DatabaseEndpoint, InstanceProfile = none | NimbusUrl `http://nimbus-alb-364314430.us-east-1.elb.amazonaws.com`; AutoScalingGroup `nimbus-app-asg`; TargetGroup `nimbus-app-tg`; DatabaseEndpoint `nimbus-db.cdgyu2umrhtq.us-east-1.rds.amazonaws.com`; InstanceProfile `none`. Also DatabaseName, PrivateSubnets, VpcId. DBPassword shows `****`. | PASS | 13:17–13:18 | A2_outputs_1.png, A2_outputs_2.png |
| A3 | Deployed code | Sidebar shows "Nimbus 0.11.0 · commit ff18611 · server ip-… · server started …". Log contains "…deployed commit ff18611 from branch main (requested commit: ff18611)". No password and no `mysql+pymysql://` line. | Sidebar: as expected (server ip-10-0-2-73). Log: `nimbus-setup: deployed commit ff18611 from branch main (requested commit: latest)`. **Requested commit is "latest", not ff18611.** I found no line containing a password or `mysql+pymysql://`. The only database line is `Connected to mysql+pymysql at nimbus-db…:3306. Tables ready. Row counts: clients 0, discussions 0…`. | **FAIL** (requested commit) | 13:19–13:20 (log); 13:29–13:30 (sidebar) | A3_system_log_deployed_commit.png, A3_app_sidebar_version_commit_server.png |
| A4 | RDS nimbus-db | Available; Publicly accessible No; VPC nimbus-vpc; subnet group nimbus-db-subnets; SG nimbus-db-sg | Available; Publicly accessible No; VPC nimbus-vpc; SG nimbus-db-sg (sg-0dbeb01e271e9cd98; group name `nimbus-DbSecurityGroup-7SBoU3521ejt`). **Subnet group is `nimbus-dbsubnetgroup-fpq2cw0qsjng`, not `nimbus-db-subnets`.** Also: us-east-1a, db.t3.micro, Internet access gateway Disabled. | **FAIL** (subnet group name) | 13:20–13:21 | A4_rds_summary_available.png, A4_rds_connectivity_security.png |
| A5 | SG inbound rules | alb-sg: 80 from 0.0.0.0/0 only. app-sg: 8501 from the alb-sg sg- ID; 22 from 127.0.0.1/32 only. db-sg: 3306 from the app-sg sg- ID only. | nimbus-alb-sg (sg-08a72c979cfd2bd26): 1 rule, HTTP TCP 80 from 0.0.0.0/0. nimbus-app-sg (sg-0916a967936cce6a8): 2 rules, TCP 22 from 127.0.0.1/32 and TCP 8501 from sg-08a72c979cfd2bd26. nimbus-db-sg: 1 rule, TCP 3306 from sg-0916a967936cce6a8. | PASS | 13:22 | A5_sg_alb_inbound.png, A5_sg_app_inbound.png, A5_sg_db_inbound.png |
| A6 | Server not directly reachable | `http://<public IP>:8501` times out; NimbusUrl loads | `http://54.205.204.75:8501/` never loaded in Chrome on two attempts. The tab stayed "loading" from 13:24:45 to 13:28:36, and again from 13:30:0x to 13:32:30. A supplementary curl from the tester's workspace timed out after 20 s at 13:25:43. NimbusUrl loads (A3 and B screenshots). **No screenshot of the timeout:** the extension cannot capture a tab that is still loading. | PASS (observed, no screenshot) | 13:24–13:32 | none for the IP; NimbusUrl: A3_app_sidebar_version_commit_server.png |
| A7 | Private route table | Only the "local" route | nimbus-rtb-private (rtb-09458fa18e403a3df): Routes (1), 10.0.0.0/16 → local, Active | PASS | 13:23 | A7_rtb_private_routes_local_only.png |
| A8 | Instance summary | IAM role "–"; record ASG, AZ, subnet | i-0f4e3fa3108bbae42: IAM role –; ASG nimbus-app-asg; AZ us-east-1b; subnet-0897cb43efba2f459 (nimbus-public-b); private IP 10.0.2.73; launched 13:08 | PASS | 13:19 | A8_instance_summary_iam_role_asg_subnet.png |
| A9 | ASG and target group | ASG: Desired 1, Min 1, Max 3; 2 subnets / 2 AZs; health check ELB. TG: 1 healthy target; stickiness on (LB cookie). | Desired 1; limits 1–3; At desired capacity; created 13:08:14. AZs us-east-1b and us-east-1a; subnets subnet-0897cb43efba2f459 and subnet-04179a0cd9d8662c9. Health check type "EC2, ELB", grace 900 s. TG: 1 total, 1 healthy. Stickiness On, "Load balancer generated cookie", 1 day. | PASS | 13:23–13:24 | A9_asg_capacity_1_1_3.png, A9_asg_network_healthcheck.png, A9_tg_targets_1_healthy.png, A9_tg_attributes_stickiness.png |
| B1 | New client + comparison | QA-1031-A "QA Test Holdings", AAPL and MSFT; chart shows both | Generated at 13:33. AAPL $344.63 and MSFT $521.91 (closes of 30 Oct 2026). The share-price chart shows both lines. | PASS | 13:32–13:35 | B1_generated_unsaved.png, B1_price_cards_chart.png, B1_share_price_chart_both.png |
| B2 | Comparison table + trends | Revenue growth, net margin, D/E for both; trend charts + table | Revenue growth 6.4% / 17.8%; net margin 26.9% / 40.3%; D/E 1.34x / 0.13x. Three trend charts. The "Trend figures by fiscal year" table opens with figures. | PASS | 13:34–13:35 | B2_comparison_table.png, B2_trend_charts.png, B2_trend_table.png |
| B3 | Financials formatting | e.g. $416.16B, not scientific | All values are $…B (e.g. AAPL revenue FY Sep 2025 $416.16B). No scientific notation anywhere in the tab. | PASS | 13:35 | B3_financials_formatted.png |
| B4 | News sources | Every article shows a source; count summaries; note status line | 6 articles (5 AAPL, 1 MSFT). All show a source: Investing.com, Investor's Business Daily, Bloomberg, TheStreet, and 2× "via Yahoo Finance RSS (publisher not listed)". **6 of 6 have a summary.** Status line: "For this comparison: AAPL: Yahoo's news feed was empty, so articles come from Yahoo search, with summaries and extra articles from Yahoo's RSS feed. MSFT: Yahoo's news feed was empty, so articles come from Yahoo's RSS feed (publishers not listed)." | PASS | 13:36 | B4_news_status_line.png, B4_news_sources_2.png, B4_news_publisher_not_listed.png |
| B5 | Save discussion | Interests saved; confirmation; second save does not create a 2nd record | Toast: "Discussion with QA-1031-A saved". The page shows "✓ Saved", "This discussion snapshot was saved", file `QA-1031-A__AAPL-MSFT__20261031T053753Z__da222206.md`. After saving, **no Save button is offered** (top or form), so a second save cannot be made from the UI. History stays at 1 discussion. | PASS | 13:37–13:38 | B5_interests_entered.png, B5_saved_confirmation_toast.png, B5_saved_no_resave_button.png |
| B6 | History caption | "Database: mysql+pymysql at nimbus-db.….rds.amazonaws.com:3306 · 1 client, 1 discussion, 2 company records" | Exactly: "Database: mysql+pymysql at nimbus-db.cdgyu2umrhtq.us-east-1.rds.amazonaws.com:3306 · 1 client, 1 discussion, 2 company records." | PASS | 13:38 | B6_history_caption_counts.png |
| B7 | Search and reopen | Client search: banner, note, "Values at the time…". Company "microsoft": same. Today's date range: found. | Client QA-1031-A: 1 row. Opened: "Historical snapshot. Discussion on 31 Oct 2026; saved 31 Oct 2026, 13:37 SGT; data retrieved 31 Oct 2026, 13:33 SGT…", interests, values table. "microsoft" (All clients): 1 row; identical values. Range 2026/10/31–2026/10/31: 1 row. | PASS | 13:39–13:42 | B7_search_by_client_result.png, B7_client_historical_snapshot_banner.png, B7_client_note_interests.png, B7_client_values_at_time.png, B7_search_company_microsoft.png, B7_company_open_values_same.png, B7_search_by_date_range_found.png |
| B8 | Markdown download | File contains client ID, interests, both tickers with stock price, news sources | "Download as Markdown" was clicked. The download response was captured in the page (6,506 characters). It contains `# Nimbus client discussion: QA-1031-A · AAPL, MSFT`, Client ID QA-1031-A (QA Test Holdings), the interests, discussion ID da222206-4d5a-4800-be6a-2585a7e77deb, "Stock price at discussion (close) \| $344.63 (2026-10-30) \| $521.91 (2026-10-30)", and 6 news items each with a source. No password and no `mysql+pymysql://`. | PASS | 13:40 | none (the content was captured as text; see §5) |
| B9 | Invalid input | ZZZZZ reported, AAPL still loads; "QA 1031" rejected | "⚠️ 1 company was not included" → "ZZZZZ: Yahoo Finance has no price data for this symbol." AAPL comparison generated at 13:45, reusing data retrieved at 13:33. "QA 1031" → "⚠ A client ID is 1–32 letters, digits, - or _, starting with a letter or digit, e.g. C-1001." | PASS | 13:45–13:46 | B9_invalid_ticker_reported_aapl_loads.png, B9_client_id_with_space_rejected.png |
| — | SERVER-1 | — | **ip-10-0-2-73** (i-0f4e3fa3108bbae42) | — | 13:29 | A3_app_sidebar_version_commit_server.png |
| C1 | Before load | Desired 1; 1 healthy; 4 TargetTracking alarms + states | Desired 1, limits 1–3. TG 1/1 healthy (screenshot ~40 s after load start). 4 alarms: AlarmHigh-1b83f91c (RequestCountPerTarget > 1000, 3 of 3 min) OK; AlarmHigh-3b204845 (CPU > 60) OK; AlarmLow-112ad6b8 (RequestCountPerTarget < 700, 15 of 15 min) **In alarm** since 13:25:21; AlarmLow-487d19d0 (CPU < 42) **In alarm** since 13:20:50. | PASS | 13:42–13:44 | C1_asg_desired_1_before.png, C1_alarms_before.png, C1_alarms_before_2.png, C1_tg_1_healthy_before.png |
| C2 | Start load | CloudShell (or PowerShell); note start and method | CloudShell, 20 parallel curl loops × 600 s. Probe returned HTTP 200. "LOAD START 2026-10-31 13:43:57 SGT". | PASS | 13:43:57 | C2_cloudshell_load_start.png |
| C3 | Alarm + metric | Request AlarmHigh "In alarm" within ~3–6 min; RequestCountPerTarget > 1,000 | AlarmHigh-1b83f91c went to In alarm at **13:49:38** (5 min 41 s after start; still OK at 13:48:07). RequestCountPerTarget (Sum, 1 min) was about 6.2K/min from about 13:44. | PASS | 13:49:50 (alarm), 13:54 (metric) | C3_request_alarmhigh_in_alarm_graph.png, C3_metric_requestcountpertarget_above_1000.png |
| C4 | Scale-out activity | "Launching a new EC2 instance … in response to an alarm"; Desired becomes 2 | Two activities "Launching a new EC2 instance: i-0fc081ae2e72f6e22" and "…: i-0739613cfe9ddd9b8", started 13:49:51. Cause: "At 2026-10-31T05:49:38Z a monitor alarm TargetTracking-nimbus-app-asg-AlarmHigh-1b83f91c-… in state ALARM triggered policy nimbus-RequestScalingPolicy-YXENZq1BUZGo changing the desired capacity from 1 to 3…". **Desired became 3, not 2.** The activities completed at 13:59:56 (end of warm-up). | **FAIL** (Desired 3 ≠ 2; scaling itself worked) | 13:50–13:52 | C4_asg_activity_launch_cause.png, C4_asg_desired_3.png |
| C5 | Targets healthy | 2 targets, both healthy; record AZs | **3 targets, all Healthy** at my first check after launch: i-0739613cfe9ddd9b8 us-east-1b; i-0fc081ae2e72f6e22 us-east-1a; i-0f4e3fa3108bbae42 us-east-1b. Healthy within ≤ 6 min of launch. I did not check between 13:50 and 13:55, so the exact moment is unknown. | **FAIL** (3 targets ≠ 2; same cause as C4) | 13:55 | C5_tg_3_targets_healthy.png |
| C6 | Any server, same data | Reach a server ≠ SERVER-1; reopen QA-1031-A: same values and note | Attempt 1: ip-10-0-2-73. Attempt 2: ip-10-0-2-73. **Attempt 3: ip-10-0-2-34 (SERVER-2)**. Attempt 4: ip-10-0-0-180. The reopen check was done on ip-10-0-0-180, a server other than SERVER-1. It showed caption 1/1/2, the same banner, interests and identical values. After scale-in, SERVER-2 (ip-10-0-2-34) also showed identical values (C7). Method: see §5. | PASS (4 attempts) | 13:56–13:58 | C6_server3_history_counts.png, C6_other_server_banner_note.png, C6_other_server_values_same.png |
| C7 | Scale-in | Scale-in alarm In alarm; "Terminating EC2 instance … in response to an alarm"; Desired back to 1; counts unchanged; B7 identical | Load traffic reached ~0 at about 13:54 (C7_metric_load_stopped). At 14:04 the request AlarmLow was OK (it had left alarm at 13:47:20). It went **In alarm at 14:11:20**. Activity: "Terminating EC2 instance: i-0f4e3fa3108bbae42" (SERVER-1, the original) from 14:11:34 to 14:12:46, cause "…AlarmLow-112ad6b8… in state ALARM triggered policy… changing the desired capacity from 3 to 2". Then "Terminating EC2 instance: i-0fc081ae2e72f6e22" at 14:12:23 (2 → 1). **Desired 1** at 14:13. Survivor: i-0739613cfe9ddd9b8 = ip-10-0-2-34. History still "1 client, 1 discussion, 2 company records"; QA-1031-A reopened with identical values. Nothing other than the alarms changed capacity. | PASS | 14:04–14:16 | C7_metric_load_stopped.png, C7_scalein_alarmlow_in_alarm.png, C7_asg_activity_terminating.png, C7_asg_desired_back_to_1.png, C7_after_scalein_history_counts_unchanged.png, C7_after_scalein_reopen_values_same.png |
| D1 | Before | Note server, History counts, time | Approved in the chat ("D Approved") at about 14:20. Server **ip-10-0-2-34** (i-0739613cfe9ddd9b8), server started 13:56 SGT. History: 1 client, 1 discussion, 2 company records. | PASS | 14:20 | D1_before_server_counts.png |
| D2 | Terminate one instance | EC2 → the single running nimbus-app → Terminate (this one only) | Exactly one running nimbus-app instance was listed (i-0739613cfe9ddd9b8, us-east-1b). The confirmation dialog listed only that ID. I clicked "Terminate (delete)" and got "Successfully initiated termination (deletion) of i-0739613cfe9ddd9b8"; state Shutting-down. | PASS | ≈14:22:35 | D2_single_instance_before.png, D2_terminate_dialog_one_instance.png, D2_termination_initiated.png |
| D3 | Unhealthy/draining; replacement; time to recover; 502/503 pages | Target unhealthy or draining; Activity shows replacement; NimbusUrl back in about 8–12 min | Target group: **0 targets** at my first check (≈14:23:15). The target had already been deregistered, so I never saw an "unhealthy" or "draining" state (deregistration delay is 30 s). NimbusUrl at 14:23:28: **"503 Service Temporarily Unavailable"**. Activity: "Terminating EC2 instance: i-0739613cfe9ddd9b8 … in response to an EC2 health check indicating it has been terminated or stopped" (14:23:59 → 14:24:31). "Launching a new EC2 instance: i-0d090b1d8f5177754 … in response to an unhealthy instance needing to be replaced" (14:24:01 → 14:24:07). NimbusUrl worked again at **14:26:22**, which is **about 4 min** after the terminate. No 502 was seen. | PASS (draining/unhealthy not observed) | 14:23–14:26 | D3_tg_0_targets.png, D3_nimbusurl_503.png, D3_asg_activity_replacement_launch.png, D3_nimbusurl_recovered_new_server.png |
| D4 | After recovery | New server name and new "server started"; counts unchanged; QA-1031-A identical | New server **ip-10-0-2-70**, "server started 31 Oct 2026, 14:26 SGT", commit ff18611. History: 1 client, 1 discussion, 2 company records. QA-1031-A (1 saved) reopened with the same banner (saved 13:37, retrieved 13:33), interests and identical values. Target group: 1 healthy target. | PASS | 14:26–14:28 | D4_new_server_history_counts.png, D4_reopen_banner_new_server.png, D4_reopen_values_same.png, D4_tg_1_healthy_replacement.png |

## 3. Timeline (section C)

| Step | Time (SGT) | Minutes from previous step | Source |
|---|---|---|---|
| Load start (CloudShell) | 13:43:57 | — | C2 screenshot |
| Request AlarmHigh → In alarm | 13:49:38 | +5.7 | alarm "Last state update" |
| Launch of 2 instances (Desired 1 → 3) | 13:49:51 | +0.2 | ASG activity start time |
| All 3 targets healthy (first observed) | ≤ 13:55 | ≤ +5.2 | target group |
| Load stop (traffic ~0) | ≈ 13:54 | (the load ran in parallel) | CloudWatch RequestCount; 600 s loops |
| Launch activities complete (warm-up end) | 13:59:56 | — | ASG activity end time |
| Request AlarmHigh → OK | 13:57:38 | — | alarm list |
| Request AlarmLow (scale-in) → In alarm | 14:11:20 | ≈ +17.3 after load stop | alarm list |
| Terminate i-0f4e3fa3108bbae42 (Desired 3 → 2) | 14:11:34 → 14:12:46 | +0.2 | ASG activity |
| Terminate i-0fc081ae2e72f6e22 (Desired 2 → 1) | 14:12:23 | +0.8 | ASG activity |
| Desired = 1 observed | ≈ 14:13:45 | +1.4 | ASG capacity overview |

Totals: load start to scale-out alarm 5 min 41 s. Load stop to back at Desired 1 about 19–20 min.

**Section D timeline**

| Step | Time (SGT) | Minutes from previous step | Source |
|---|---|---|---|
| Terminate i-0739613cfe9ddd9b8 (ip-10-0-2-34) | ≈ 14:22:35 | — | console banner |
| Target group shows 0 targets | ≈ 14:23:15 | +0.7 | target group |
| NimbusUrl returns 503 | 14:23:28 | +0.2 | browser |
| ASG detects it and starts the replacement terminate | 14:23:59 | +0.5 | ASG activity |
| Replacement i-0d090b1d8f5177754 launched | 14:24:01 | +0.0 | ASG activity |
| NimbusUrl works again (ip-10-0-2-70) | 14:26:22 | +2.4 | browser |
| 1 healthy target confirmed | 14:28 | — | target group |

Total outage: about 4 min (expected 8–12). I did not load NimbusUrl between 14:23:28 and 14:26:22 (2.9 min, slightly more than the 2-minute interval asked for). During that gap I checked the ASG activity twice instead. The exact moment the app came back may therefore be earlier than 14:26:22.

## 4. Defects and observations

**D-1. Medium. The stack was deployed without a pinned commit.**

- Message (EC2 system log, i-0f4e3fa3108bbae42): `nimbus-setup: deployed commit ff18611 from branch main (requested commit: latest)`.
- The stack's Parameters tab shows `GitCommit` as `-` (empty). The brief says the stack was created with GitCommit = ff18611.
- Every server the Auto Scaling group adds clones the *latest* `main`. A push to `main` during the demo would put mixed versions behind the load balancer. The scale-out servers in this run happened to get ff18611 because `main` was still at ff18611.
- Steps to reproduce: EC2 → Instances → nimbus-app → Actions → Monitor and troubleshoot → Get system log, then search for `nimbus-setup: deployed commit`.
- Screenshot: A3_system_log_deployed_commit.png.

**D-2. Low. The RDS subnet group name does not match the guide.**

- The guide says `nimbus-db-subnets`; the actual name is `nimbus-dbsubnetgroup-fpq2cw0qsjng`.
- Steps to reproduce: RDS → nimbus-db → Connectivity & security → Endpoints → Additional configurations.
- Screenshot: A4_rds_connectivity_security.png.
- Either name the subnet group in the template or update the guide and the "What the stack creates" table.

**D-3. Low (documentation). The scale-out expectation does not match target-tracking behaviour.**

- The guide and checklist expect Desired 2 and 2 targets. Target tracking calculated about 6.2K requests per target against a target of 1,000, so it went straight to MaxServers: Desired **1 → 3**.
- Message: "…triggered policy nimbus-RequestScalingPolicy-YXENZq1BUZGo changing the desired capacity from 1 to 3."
- Screenshots: C4_asg_activity_launch_cause.png, C4_asg_desired_3.png, C5_tg_3_targets_healthy.png.
- Also, the activity cause text reads "a monitor alarm … in state ALARM triggered policy", not literally "in response to an alarm".

**D-4. Low (question for the team). SERVER-1's "server started" time is later than the server's start.**

- The sidebar on ip-10-0-2-73 showed "server started 31 Oct 2026, 13:28 SGT".
- The instance launched at 13:08, and the app passed its health check before the SUCCESS signal at 13:09:47.
- Either the service restarted at about 13:28, or "server started" records something other than process start. The new servers showed 13:56, which is consistent with their install time.
- I could not tell which from the console (no SSH by rule).
- Screenshot: A3_app_sidebar_version_commit_server.png.

**D-5. Low (cosmetic). The client-ID warning breaks the form layout.**

- After typing "QA 1031", the warning text pushes the Client dropdown below the Client ID field, so the first row of the form is misaligned.
- Screenshot: B9_client_id_with_space_rejected.png.

**Observations (not defects)**

- **Alarm baseline.** At rest, both AlarmLow alarms are *In alarm*. The guide's C1 text expects "all OK (or Insufficient data)". This is normal for target tracking at MinServers.
- **Scale-in removed the original server.** The first scale-in terminated i-0f4e3fa3108bbae42 (SERVER-1). Any user sticky to it loses unsaved work, as the design notes describe. Saved data was unaffected.
- **Per-server load after scale-out.** With 3 servers, the load was ~2K requests per target per minute, still above target. This was capped by MaxServers 3.
- **The new servers came up faster than documented.** They were healthy in ≤ 6 min, versus the 6–10 min the guide states.

## 5. Not checked, or checked differently, and why

- **A6 screenshot:** the extension cannot capture a tab that is still loading. I observed the timeout but have no image.
- **C6 private windows:** the extension cannot open incognito windows. For each attempt I deleted the load balancer's stickiness cookie (`AWSALB`) in a new tab before loading NimbusUrl. This gives the same effect as a fresh private window.
- **C6 server used:** SERVER-2 (ip-10-0-2-34) was first reached on attempt 3. The reopen check was done on attempt 4's server (ip-10-0-0-180), also ≠ SERVER-1. SERVER-2 itself was checked after scale-in (C7) with identical results.
- **B8 file:** I clicked the download, but I have no access to your Downloads folder. I verified the file's content by capturing the same download response in the page.
- **C2/C7 "LOAD END" line:** the CloudShell session was recycled while its tab was in the background, so the final "LOAD END" line was never displayed. The stop time (~13:54) comes from CloudWatch RequestCount, which matches the 600 s loop. At 14:17 I pressed Ctrl+C in CloudShell to make sure nothing was still running. It showed "Waiting for the environment to run…", meaning the old session had already ended.
- **C5 exact time-to-healthy:** I did not watch the targets between 13:50 and 13:55.
- **Rule deviation (disclosure):** while confirming DBPassword shows `****`, my script read the visible values of other parameters as text. I took no screenshot of the Parameters tab. This is how the empty GitCommit (D-1) was found.
- **Section D:** run after "D Approved" was written in the chat (about 14:20). The "unhealthy/draining" state was not observed: by my first check, 40 s after the terminate, the target had already been removed. Recovery took about 4 min, faster than the guide's 6–10 min.
- **Not changed:** apart from the one approved terminate in D2, no stack, parameter, security group, target group, scaling setting, RDS or IAM setting was changed. No SSH was used. Only the fictional client QA-1031-A was saved; "QA 1031" was rejected and never saved, and QA-1031-B was not needed.

## 6. Final verdict

- **A, Deployment and security: PASS with 2 findings.** Network isolation, security groups, RDS privacy, IAM and the stack signal are all correct. The commit was not pinned (D-1, Medium) and the subnet group name differs from the guide (D-2, Low).
- **B, App through the load balancer: PASS.** All 9 checks passed.
- **C, Automatic scaling: PASS in behaviour.** Scale-out on the request alarm, data shared across servers, and alarm-driven scale-in back to 1 all worked, with saved data intact. C4 and C5 are FAIL only against the written expectation of 2 servers; target tracking went to 3 (D-3).
- **D, Self-healing: PASS.** After the only server was terminated, a replacement launched automatically within about 1.5 min. NimbusUrl showed 503 and was working again on a new server about 4 min after the terminate, with all saved data unchanged.
