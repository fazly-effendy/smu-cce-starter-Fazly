# Evidence: automatic scaling on AWS (Feature 6), 31 Oct 2026

**What was tested.**
- Deployment of `main` at commit **`ff18611`** (Nimbus 0.11.0) with
  `scripts/nimbus-stack.yaml` in the AWS Academy Sandbox (us-east-1).
- Stack `nimbus`, created 13:01–13:09 SGT.
- Testing ran 13:15–14:28 SGT.

**How it was checked.**
- An independent check followed
  [`docs/aws-deployment.md`](../../aws-deployment.md), "Evidence to capture",
  sections A–D. It changed nothing except using the app, a 10-minute load test
  and one approved server termination.
- Test client: `QA-1031-A` (fictional).
- Account IDs, user names and ARNs are blacked out. All 72 screenshots were also
  text-scanned for account numbers, ARNs and keys; none were found.
- The full report is in [`QA-REPORT.md`](QA-REPORT.md).

**Verdict:** all four sections pass in behaviour.

| Section | Result | Key evidence |
|---|---|---|
| A. Deployment and security | PASS, 2 findings (fixed in v0.11.1) | Stack `CREATE_COMPLETE` with the Auto Scaling group's SUCCESS signal (A1); only the load balancer is public; servers accept 8501 only from it, and RDS 3306 only from the servers (A5); a server's own address times out (A6); RDS not publicly accessible (A4); no IAM role (A8) |
| B. The app through the load balancer | PASS, 9 of 9 | Comparison, financials, news (6 of 6 articles with a summary and a source), save, history on RDS, search by client, company name and date, download, invalid input (B1–B9) |
| C. Automatic scaling | PASS in behaviour | Load test → alarm → 1 → 3 servers → all healthy → a discussion saved on one server reopens on the others → load stops → alarms scale back to 1, data intact (C1–C7) |
| D. Self-healing | PASS | The only server terminated → 503 → the group launched a replacement in under 2 minutes → the app back in about 4 minutes on a new server, data intact (D1–D4) |

The single best screenshot is
[`D3_asg_activity_replacement_launch.png`](D3_asg_activity_replacement_launch.png).
Its Activity history shows the whole story:
1. scale-out 1 → 3 on the request alarm;
2. scale-in 3 → 2 → 1 on the low-load alarm;
3. the terminated server replaced after a health check.

## Timeline

| Step | Time (SGT) |
|---|---|
| Load test starts (CloudShell, 20 parallel `curl` loops, 10 minutes) | 13:43:57 |
| Requests per server about 6,200 a minute (target 1,000) | from about 13:44 |
| Scale-out alarm *In alarm* | 13:49:38 |
| Two servers launched: desired capacity 1 → 3 | 13:49:51 |
| All 3 servers healthy behind the load balancer | by 13:55 |
| Load stops | about 13:54 |
| Scale-in alarm *In alarm* | 14:11:20 |
| Servers terminated: 3 → 2 → 1 | 14:11:34 and 14:12:23 |
| One server terminated by hand (section D, approved) | about 14:22:35 |
| Replacement launched after a health check | 14:24:01 |
| App working again on the new server | 14:26:22 |

## Findings and what was done

| # | Finding | Severity | Fixed in v0.11.1 |
|---|---|---|---|
| D-1 | The stack was created with `GitCommit` empty (system log: "requested commit: latest"). Servers added later would clone the newest commit, so different servers could run different code. In this run all servers got `ff18611`, because `main` did not change. | Medium | `GitCommit` is now required by the template (`tests/test_cloudformation.py`) |
| D-2 | The guide named the DB subnet group `nimbus-db-subnets`; that is its Name tag, and the real name is generated (`nimbus-dbsubnetgroup-…`) | Low | Guide corrected. Not renamed in the template: that would replace the database |
| D-3 | The guide expected 1 → 2 servers. Target tracking scales in proportion to the load (6,200 against 1,000), up to the maximum of 3 | Low (docs) | Guide explains it; a lighter load (about 4 loops) gives 1 → 2 |
| D-4 | "Server started 13:28" on a server whose app started at 13:08: the time was the first page view | Low | Read from the operating system (`tests/test_qa_regressions.py`) |
| D-5 | The Client ID warning pushed the client fields out of line | Low | Warning below the row (`tests/test_qa_regressions.py`) |
| Obs. | At rest, the two scale-in (*AlarmLow*) alarms are *In alarm* | Expected | Guide explains it |

## Limits of this evidence

- **Not tested here:** deploying new code by **Update stack** (the rolling update).
  The stack was only created, never updated.
- **v0.11.1 itself is not deployed yet.** Its changes are a required parameter,
  two small app fixes and documentation, all tested locally.
- Section A6 (a server's own address times out) was observed, but the browser
  could not screenshot a page that never loads.
- Section C6 reached other servers by clearing the load balancer's stickiness
  cookie instead of private windows. The effect is the same.
- Times come from the AWS console. Alarm and activity times shown in UTC were
  converted to SGT (+8 h).
