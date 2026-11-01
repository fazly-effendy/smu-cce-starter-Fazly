# Evidence: deploying new code by updating the stack (rolling update), 1 Nov 2026

**What was tested.**
- **Update stack** on the running stack `nimbus` (AWS Academy Sandbox, us-east-1),
  changing only `GitCommit`, from **`ff18611`** (Nimbus 0.11.0) to **`e27a8e7`**
  (Nimbus 0.11.1).
- The design is in [`docs/aws-deployment.md`](../../aws-deployment.md), *Keeping saved
  discussions*.

**How it was checked.**
- An independent check ran 11:27–12:22 SGT. The full report is in
  [`QA-REPORT.md`](QA-REPORT.md).
- Account IDs are blacked out. All 47 screenshots were text-scanned for account
  numbers, ARNs and keys; none were found.

**How the test was set up (disclosed in the report).**
- The 31 Oct stack had been deleted on 31 Oct (15:44 SGT), together with its
  database and the test discussion `QA-1031-A`.
- A new stack was created at 11:21 SGT, directly on `e27a8e7`.
- To have an older version to update from, the tester (at the team's request)
  first updated the stack to `ff18611`, then measured the update back to `e27a8e7`.

**Verdict**

| Question | Result |
|---|---|
| Is the new code deployed by **Update stack**? | **Yes.** Before: `Nimbus 0.11.0 · commit ff18611 · server ip-10-0-0-188`. After: `Nimbus 0.11.1 · commit e27a8e7 · server ip-10-0-2-40`. The system log reads `deployed commit e27a8e7 … (requested commit: e27a8e7)`, and the v0.11.1 layout fix is visible (P8). |
| One server at a time, without an outage? | **Yes, as observed.** The group added the new server, waited for its success signal, and only then removed the old one. The update took 2 minutes in total. No 502/503 was seen, though with checks about 2 minutes apart a very short gap cannot be ruled out. |
| Is the database left alone? | **Yes.** `NimbusDatabase` has no update events; RDS kept its creation time and stayed *Available*. The change preview listed only the launch template, the Auto Scaling group and the two scaling policies. |
| Do saved discussions survive? | **Not shown here.** The database was new and empty (0 clients before and after), so there was nothing to compare. To be shown in the next update, with a discussion saved first. |

The key screenshot is
[`U8_events_2_signal_and_terminate.png`](U8_events_2_signal_and_terminate.png):
*Received SUCCESS signal* from the new server at 12:09:55, then *Terminating
instance(s)* for the old one at 12:09:56.

## Timeline (12:08:02 = update started)

| Time (SGT) | Step |
|---|---|
| 12:08:02 | Stack `UPDATE_IN_PROGRESS` |
| 12:08:12 | Launch template updated |
| 12:08:18 | Rolling update starts: *"Temporarily setting autoscaling group MinSize and DesiredCapacity to 2"* |
| 12:08:28 | New server launched |
| 12:09:55 | *Received SUCCESS signal* from the new server |
| 12:09:56–58 | Old server terminated |
| 12:10:04 | Stack `UPDATE_COMPLETE` (2 min 2 s) |

## Findings

| # | Finding | What was done |
|---|---|---|
| D1 | The 31 Oct stack was deleted, so its test data was lost. | The guide now warns at the top that deleting the stack deletes every saved discussion. The stack is kept from now on. |
| D2 | The History tab shows the database driver and host (never the password). | Kept on purpose: it is the visible proof in the demo that search runs on RDS (README, *Known limitations*). |
| D3 | The tester ran the updates at the team's request, so the person checking was also the one changing the stack. | Disclosed in the report. |
| Obs. | Chrome's HTTPS-first setting blocked the `http://` address until **Continue to site** was clicked. | Added to the guide's troubleshooting and the deploy steps: open the address once before a demo. |
