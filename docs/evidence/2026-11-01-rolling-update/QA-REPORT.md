# Nimbus code-update QA report: CloudFormation "Update stack" (0.11.0 → 0.11.1)

## 1. Header

| Item | Value |
|---|---|
| Date | Sunday 1 Nov 2026, 11:27 – 12:22 SGT |
| Tester | Claude (Claude in Chrome), for Fazly / SMU DS600 group |
| Browser | Google Chrome with the Claude in Chrome extension. All checks ran in one tab. The `AWSALB`/`AWSALBCORS` cookies were deleted before each app reload instead of opening a private window (see section 6). |
| Stack | `nimbus`, us-east-1, AWS Academy Sandbox |
| Stack status before | **CREATE_COMPLETE**. The stack was created **1 Nov 2026 11:21:17 SGT**, not on 31 Oct as the test plan says. |
| Stack status after | **UPDATE_COMPLETE** at 12:10:04 SGT |
| Old version / commit / instance | Plan: 0.11.0 · ff18611. **Found at start: 0.11.1 · e27a8e7** on i-0c8ca5796294c76eb (ip-10-0-2-201). For the measured update: **0.11.0 · ff18611** on **i-0c1c21d53586b6fc5 (ip-10-0-0-188)** |
| New version / commit / instance | **0.11.1 · e27a8e7** on **i-0369ecbe99f9d7cf7 (ip-10-0-2-40)** |
| RDS started by tester? | **No.** nimbus-db was already Available. |
| **Deviations from the test rules** | **Rule 1:** the tester ran both stack updates, because the team member asked for it in chat ("update for me"). In both updates only the `GitCommit` parameter changed; every other parameter stayed at "Use previous value". **Two-step update:** the stack was already on e27a8e7, so with the team member's agreement it was first updated to ff18611 (12:00:45–12:03:03) to get a 0.11.0 baseline. The 0.11.0 → 0.11.1 update measured in Phase 2 ran 12:08:02–12:10:04. |

## 2. Results

| ID | Check | Expected | Actual | Result | Time (SGT) | Screenshots |
|---|---|---|---|---|---|---|
| U1 | Stack status + NimbusUrl | CREATE/UPDATE_COMPLETE, the 31 Oct stack | Stack was CREATE_IN_PROGRESS at 11:27, then CREATE_COMPLETE at 11:29:16. **Created 1 Nov 11:21:17.** The 31 Oct stack (created 13:01:39) was deleted on 31 Oct: DELETE_IN_PROGRESS "User Initiated" at 15:44:14, DELETE_COMPLETE at 15:46:02, and NimbusDatabase DELETE_COMPLETE at 15:45:55. NimbusUrl = `http://nimbus-alb-172823826.us-east-1.elb.amazonaws.com` | PASS with deviation (not the 31 Oct stack) | 11:27–11:30 | U1_stack_create_in_progress, U1_stack_create_complete, U1_outputs, U1_events_initial, U1_deleted_stack_31oct, U1_deleted_stack_events |
| U2 | RDS nimbus-db | Available | Available, db.t3.micro, MySQL 8.4.11. **Created 1 Nov 2026 11:25.** Manual snapshots: 0. | PASS with deviation (new database) | 11:28 | U2_rds_available, U2_rds_created_time, U2_rds_no_manual_snapshots |
| U3 | Target group: 1 healthy target | 1 healthy | 1 healthy: i-0c8ca5796294c76eb, us-east-1b, launched 11:27:34 | PASS | 11:30 | U3_target_healthy, U3_instance_old_summary, U3_instance_old_launch_time |
| U4 | ASG Desired 1 / Min 1 / Max 3 + activity history | 1 / 1–3; 31 Oct scaling visible | Desired 1, scaling limits 1–3, "At desired capacity". Activity history has 1 entry only: launch of i-0c8ca5796294c76eb at 11:27:34, nothing from 31 Oct. 4 TargetTracking alarms present. | PASS with deviation | 11:31 | U4_asg_capacity, U4_asg_activity_history, U4_alarms_baseline_4 |
| U5 | Sidebar shows 0.11.0 · ff18611 | `Nimbus 0.11.0 · commit ff18611 · server ip-… · server started …` | **`Nimbus 0.11.1 · commit e27a8e7 · server ip-10-0-2-201 · server started 1 Nov 2026, 11:28 SGT`**. The system log agrees: `nimbus-setup: deployed commit e27a8e7 from branch main (requested commit: e27a8e7)` | **FAIL** (target version already deployed) | 11:33 | U5_app_sidebar_version, U5_syslog_old_instance_already_e27a8e7 |
| U5b | Re-baseline after step 1 (ff18611) | 0.11.0 · ff18611 | `Nimbus 0.11.0 · commit ff18611 · server ip-10-0-0-188 · server started 1 Nov 2026, 12:05 SGT` = **SERVER-OLD** | PASS | 12:05 | U5b_app_baseline_0.11.0_ff18611, S1_update1_submitted_ff18611 |
| U6 | History counts + QA-1031-A | "1 client, 1 discussion, 2 company records"; QA-1031-A opens | Caption: `Database: mysql+pymysql at nimbus-db.cdgyu2umrhtq.us-east-1.rds.amazonaws.com:3306 · 0 clients, 0 discussions, 0 company records.` Client list contains only "All clients". "No saved discussions match these filters." Same at the 12:05 re-baseline. | **FAIL** (no data; banner, interests and values could not be recorded) | 11:34, 12:05 | U6_history_counts_empty, U6_client_list_no_QA-1031-A, U6b_history_counts_baseline |
| U7 | Phase 1 hand-off | Message in chat | Sent at 11:35: "PHASE 1 DONE: ready for the update. Server ip-10-0-2-201, instance i-0c8ca5796294c76eb, counts 0 clients, 0 discussions, 0 company records", plus a warning about the deviations | DONE | 11:35 | – |
| U8 | Events during update | LT UPDATE_COMPLETE, rolling update, SUCCESS signal, old terminated, UPDATE_COMPLETE | All present, in order (see section 3). No FAILED or ROLLBACK events. | PASS | 12:08:02–12:10:04 | U8_update_started, U8_events_rolling_update_started, U8_events_1_launch_template_and_rolling, U8_events_2_signal_and_terminate, U8_events_3_update_complete |
| U9 | Database untouched | No NimbusDatabase update/replacement; same creation time; Available | Events: NimbusDatabase has only its CREATE events (11:22:05–11:27:14), with no update events in either update. The change set preview listed only AppLaunchTemplate (Replacement False), AppAutoScalingGroup, CpuScalingPolicy and RequestScalingPolicy (Conditional). The timeline shows only AppLaunchTemplate and AppAutoScalingGroup. RDS: still created 1 Nov 2026 11:25 and Available. | PASS | 12:11–12:12 | U9_timeline_only_LT_and_ASG_updated, U9_rds_same_created_time, U9_rds_available_after |
| U10 | ASG activity: launch new / terminate old | Both, with cause | Launch i-0369ecbe99f9d7cf7, 12:08:29–12:08:34. Cause: "At 2026-11-01T04:08:19Z a user request update of AutoScalingGroup constraints to min: 2, max: 3, … changing the desired capacity from 1 to 2 …". Terminate i-0c1c21d53586b6fc5, 12:09:58–12:10:50. Cause: "At 2026-11-01T04:09:58Z instance i-0c1c21d53586b6fc5 was taken out of service in response to a user request, shrinking the capacity from 2 to 1." | PASS | 12:12 | U10_asg_activity_descriptions, U10_asg_activity_causes_times |
| U11 | NimbusUrl during update (every ~2 min) | App answers; note 502/503 | 12:08:25: app OK, 0.11.0 · ff18611 · ip-10-0-0-188. 12:10:14: page still rendering (Streamlit "Stop" status). 12:10:23 (same load): app OK, 0.11.1 · e27a8e7 · ip-10-0-2-40. **No 502/503 seen.** | PASS (limited sampling, see section 6) | 12:08–12:10 | U11_app_1210_new_server |
| P1 | 1 healthy target, new ID; old terminated | New healthy target; old Terminated | Target group: 1 healthy, i-0369ecbe99f9d7cf7 (new). EC2: i-0c1c21d53586b6fc5 **Terminated**, i-0c8ca5796294c76eb **Terminated**, i-0369ecbe99f9d7cf7 Running (2/2 checks). New instance launched **12:08:28**. | PASS | 12:13 | P1_target_new_healthy, P1_instances_old_terminated, P1_instance_new_summary |
| P2 | Sidebar 0.11.1 · e27a8e7, new server, start time ≈ launch | as stated | `Nimbus 0.11.1 · commit e27a8e7 · server ip-10-0-2-40 · server started 1 Nov 2026, 12:09 SGT`. **SERVER-NEW = ip-10-0-2-40**, different from SERVER-OLD ip-10-0-0-188. Server started 12:09; instance launched 12:08:28 (about 1 min apart). | PASS | 12:14 | P2_app_sidebar_0.11.1_e27a8e7, P2_instance_new_launch_time |
| P3 | System log of new instance | deploy line present; no password; no `mysql+pymysql://` | Contains `nimbus-setup: deployed commit e27a8e7 from branch main (requested commit: e27a8e7)`. A full-text scan of the 47,475-character log found 0 lines matching password/passwd/DB_PASS/secret and 0 occurrences of `mysql+pymysql://`. The log was empty until about 12:21 (13 min after launch). | PASS | 12:21 | P3_syslog_new_deployed_e27a8e7_left, P3_syslog_new_requested_commit_right |
| P4 | Data kept | Same counts and QA-1031-A values as U6 | Counts `0 clients, 0 discussions, 0 company records`, the same as before the update (U6/U6b). QA-1031-A does not exist before or after, so the field-by-field comparison could not be done. | **BLOCKED** (counts unchanged; no saved discussion to compare) | 12:15 | P4_history_counts_after |
| P5 | Search "microsoft" and 31 Oct 2026 | QA-1031-A found both times | "No saved discussions match these filters." for company "microsoft", and for "microsoft" + 2026/10/31–2026/10/31 | **FAIL / BLOCKED** (no data) | 12:15 | P5_search_microsoft_none, P5_search_date_31oct_none |
| P6 | Download Markdown | File contains QA-1031-A etc. | Nothing to download, because no saved discussion exists | **BLOCKED** | – | – |
| P7 | ASG 1/1–3; 4 TargetTracking alarms | unchanged | Desired 1, limits 1–3, "At desired capacity". 4 alarms TargetTracking-nimbus-app-asg-* (2 AlarmLow "In alarm", 1 AlarmHigh OK, 1 more), the same 4 as before. | PASS | 12:12, 12:16 | P7_asg_capacity_after, P7_alarms_after_4 |
| P8 | Layout fix (0.11.1) | Warning below row; Client / Client ID / Client name on one row | **0.11.1:** the warning "A client ID is 1–32 letters, digits, - or _, starting with a letter or digit, e.g. C-1001." appears below the row, and the 3 fields stay on one aligned row. **0.11.0 (12:05, for comparison):** the warning sat inside the Client ID column and pushed the Client and Client name fields down out of line. Not saved. | PASS | 12:14 | P8_layout_fixed_warning_below, U5b_layout_bug_0.11.0 |
| P9 | GitCommit parameter | e27a8e7 | `GitCommit = e27a8e7` (read as text; no screenshot taken) | PASS | 12:16 | – |

## 3. Update timeline (measured update ff18611 → e27a8e7)

| Time (SGT) | Step | Minutes after "update started" |
|---|---|---|
| 12:08:02 | **Update started**: stack UPDATE_IN_PROGRESS, "User Initiated" | 0:00 |
| 12:08:12 | AppLaunchTemplate UPDATE_COMPLETE | 0:10 |
| 12:08:18 | "Rolling update initiated. Terminating 1 obsolete instance(s) in batches of 1, while keeping at least 1 instance(s) in service…"; "Temporarily setting autoscaling group MinSize and DesiredCapacity to 2." | 0:16 |
| 12:08:28 | **New instance launched**: i-0369ecbe99f9d7cf7 (EC2 launch time; ASG activity 12:08:29–12:08:34) | 0:26 |
| 12:08:34 | "New instance(s) added to autoscaling group - Waiting on 1 resource signal(s) with a timeout of PT25M." | 0:32 |
| 12:09 | App on the new server reports "server started 12:09" | ~1:00 |
| 12:09:55 | **"Received SUCCESS signal with UniqueId i-0369ecbe99f9d7cf7"** (new instance healthy) | 1:53 |
| 12:09:56 | "Terminating instance(s) [i-0c1c21d53586b6fc5]; replacing with 0 new instance(s)." | 1:54 |
| 12:09:58 | **Old instance terminated**: "Successfully terminated instance(s) [i-0c1c21d53586b6fc5] (Progress 100%)." ASG termination activity ran until 12:10:50. | 1:56 |
| 12:10:00 | AppAutoScalingGroup UPDATE_COMPLETE | 1:58 |
| 12:10:04 | **Stack UPDATE_COMPLETE** | **2:02** |

**Minutes when NimbusUrl did not work:** none observed. Samples at 12:08:25 (old server) and 12:10:14–12:10:23 (new server) both returned the app. With sampling every ~2 min, an outage shorter than ~2 min cannot be ruled out (see section 6).

Step 1 (ff18611, run only to set up the baseline): started 12:00:45 → LT complete 12:00:55 → new i-0c1c21d53586b6fc5 at 12:01:14 → SUCCESS signal 12:02:55 → i-0c8ca5796294c76eb terminated 12:02:57 (ASG end 12:04:10) → UPDATE_COMPLETE 12:03:03 (2:18 total).

## 4. Values comparison (U6 vs P4)

| Field | U6 (before) | P4 (after) | Same? |
|---|---|---|---|
| History caption counts | 0 clients, 0 discussions, 0 company records | 0 clients, 0 discussions, 0 company records | Yes |
| QA-1031-A historical-snapshot banner (saved 31 Oct 2026, 13:37 SGT) | Not present | Not present | n/a |
| Interests | Not present | Not present | n/a |
| AAPL / MSFT stock price | Not present | Not present | n/a |
| Revenue growth / net margin / debt-to-equity | Not present | Not present | n/a |

**Differences found:** none. There was no saved data to lose, so this test does not show that saved discussions survive the update. U9 does show that the database resource was not touched.

## 5. Defects

**D1: Test data and pre-conditions missing (High, environment/process).**

- **Message / evidence:** Deleted stack events: `2026-10-31 15:44:14 nimbus DELETE_IN_PROGRESS User Initiated` … `15:45:55 NimbusDatabase DELETE_COMPLETE` … `15:46:02 nimbus DELETE_COMPLETE`. The current stack was created 1 Nov 11:21:17 with GitCommit e27a8e7. nimbus-db was created 1 Nov 11:25. RDS manual snapshots: 0. The app showed `0 clients, 0 discussions, 0 company records`.
- **Steps:** CloudFormation → Stacks → filter "Deleted" → nimbus (31 Oct) → Events. Then RDS → nimbus-db → Configuration → Created time. Then RDS → Snapshots → Manual.
- **Impact:** QA-1031-A (saved 31 Oct 13:37) was lost when the 31 Oct stack was deleted, and the replacement stack started on the target commit. So the "data kept" check (P4–P6) could not be run, and the planned 0.11.0 → 0.11.1 update would have changed nothing.
- **Suggestion:** stop the sandbox instead of deleting the stack, or keep a final snapshot, as in docs/aws-deployment.md "Keeping saved discussions" / "Sandbox sessions". Then save a test discussion again and re-run P4–P6.
- **Screenshots:** U1_deleted_stack_31oct, U1_deleted_stack_events, U2_rds_created_time, U2_rds_no_manual_snapshots, U5_app_sidebar_version, U6_history_counts_empty.

**D2: History tab shows database driver and endpoint to app users (Low).**

- **Message:** `Database: mysql+pymysql at nimbus-db.cdgyu2umrhtq.us-east-1.rds.amazonaws.com:3306 · 0 clients, …`
- **Steps:** open NimbusUrl → History.
- **Impact:** no password is shown. Relationship managers see internal infrastructure details (driver, RDS host, port) that they don't need. Consider showing only the counts.
- **Screenshots:** U6_history_counts_empty, P4_history_counts_after.

**D3: Update not run by the team member (Low, process).**

- **Detail:** No update had started by 11:58. At the team member's request the tester ran both updates, so the "independent tester" separation in rule 1 was not kept for this run.
- **Screenshots:** S1_update1_submitted_ff18611, U8_update_started.

No defects were found in the update mechanism itself.

## 6. Not checked, or checked differently

- **U6 / P4 / P5 / P6 (QA-1031-A values, banner, interests, Markdown download):** not possible, because the discussion does not exist (D1). Rule 5 forbids saving a new one.
- **U11 sampling:** the update finished in 2 min 2 s. With a ~2-minute interval only two loads fell inside the window (12:08:25 and 12:10:14). Short gaps between samples were not measured.
- **U11 / P2 "new private window":** the extension works in one tab, so each load was done in the same tab after deleting the `AWSALB`/`AWSALBCORS` cookies with JavaScript. They are readable from the page, so not HttpOnly.
- **First app load:** Chrome's HTTPS-only warning blocked the http:// URL until the team member clicked "Continue to site" (about 11:31–11:34).
- **P3 timing:** the EC2 console's system log for the new instance stayed empty until about 12:21, roughly 13 min after launch. This is normal console-output delay, not a defect.
- **Parameters tab:** never screenshotted. Only the GitCommit value was read (P9). DBPassword stayed at "Use previous value" in both updates and was never typed or shown.

## 7. Verdict

- **Code updated:** **YES.** A CloudFormation update of GitCommit replaced the server: 0.11.0 · ff18611 on ip-10-0-0-188 became 0.11.1 · e27a8e7 on ip-10-0-2-40. The system log and the GitCommit parameter confirm e27a8e7, and the v0.11.1 layout fix is visible.
- **One server at a time, no downtime:** **YES, as far as observed.** The rolling update added one new instance (desired 1 → 2), waited for its SUCCESS signal, and only then terminated the old one, in 2 min 2 s. No 502/503 was seen, but with ~2-minute sampling an outage under ~2 min can't be ruled out.
- **Data kept:** **NOT VERIFIED.** The database was not modified or replaced (no NimbusDatabase events, same creation time, Available) and the counts stayed at 0/0/0. But the QA-1031-A data had already been lost on 31 Oct when the previous stack was deleted, so saved discussions surviving an update could not be shown.
