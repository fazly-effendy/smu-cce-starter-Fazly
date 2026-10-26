# Evidence: Stage 2 deployment, 27 Oct 2026

Deployment of `main` at commit **c6b9b46** with `scripts/nimbus-stack.yaml` in the AWS
Academy Sandbox (us-east-1), verified by an independent check that made no changes other
than using the app and one EC2 reboot. Test marker: `AUDIT-RUN-20261026-01`.
Account IDs are not shown (one ARN is blacked out in C4d).

| # | Check | Result | Screenshots |
|---|---|---|---|
| 1 | Stack `CREATE_COMPLETE` at 00:05:40 SGT; `AppServer` received the SUCCESS signal from i-07048c037816544b8 | PASS (see note 1) | C1_cfn_events |
| 2 | Stack outputs: `NimbusUrl`, `PublicIp`, `InstanceId`, `VpcId`, `PrivateSubnets`, `DatabaseEndpoint`, `DatabaseName` | PASS | C2_cfn_outputs |
| 3 | RDS `nimbus-db`: Available, **Publicly accessible: No**, security group `nimbus-db-sg` | PASS | C3_rds_security |
| 4 | `nimbus-db-sg`: one inbound rule, TCP 3306 from `sg-0db637ae822bc6b68`, which is `nimbus-app-sg`. `nimbus-app-sg`: 8501 from anywhere, 22 from 127.0.0.1/32 only | PASS | C4a–C4d |
| 5 | App sidebar: *Nimbus 0.9.0 · commit c6b9b46*, the merge commit at the top of GitHub `main` | PASS | C5_app_version |
| 6 | MSFT + NVDA: comparison (revenue growth 17.8% / 65.5%), all 9 statement items (NVDA total liabilities N/A), the Notes tab kept every field, saved once; History shows `mysql+pymysql at nimbus-db…`, times in SGT; today's date finds it, yesterday's doesn't; from-after-to rejected; `nvda` finds it; reopened identical | PASS | C6a–C6k |
| 7 | News only about the right company | FAIL, fixed in v0.9.1 (note 2) | C7a–C7c |
| 8 | Reboot: counts 1 / 2 / 1 before and after; the briefing reopened with the same values and note | PASS | C8a–C8d |

**Note 1.** CloudFormation shows the text *"Received SUCCESS signal with UniqueId …"* for a
successful signal; it does not display the custom reason. The deployed commit is proven by the app sidebar (check 5). From v0.9.1 it is also in the EC2 system log
(line `nimbus-setup: deployed commit …`).

**Note 2.** Yahoo search linked general articles (e.g. *Why PagSeguro Stock Crashed Today*)
to NVDA. From v0.9.1 an article is kept only if Yahoo links it to the ticker **and** its
headline or summary names the company. The other low-severity findings (meeting date and
saved news dates in UTC; results shown under the date error; narrow date boxes) are also
fixed in v0.9.1, and the sidebar now shows when the server started, so a reboot is visible.
