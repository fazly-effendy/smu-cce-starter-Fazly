# Deploying Nimbus to the AWS Academy Sandbox

Template: [`scripts/nimbus-stack.yaml`](../scripts/nimbus-stack.yaml) (CloudFormation).
Region: **us-east-1** (the only region the Sandbox allows).

The deployment is built in stages. Each stage is the same template, extended:

| Stage | Adds | Status |
|---|---|---|
| 1 | VPC (2 public + 2 private subnets), security group, EC2 app server installed by user data, systemd service, health-checked `CREATE_COMPLETE` | Template ready |
| 2 | Amazon RDS for MySQL in the private subnets; database security group that accepts MySQL only from the app server | Next |
| 3 | Scaling, per the Week 9 lesson | After Week 9 |

## What Stage 1 creates

| Resource | Name tag | Purpose |
|---|---|---|
| VPC 10.0.0.0/16 | `nimbus-vpc` | Private network for Nimbus |
| Internet gateway | `nimbus-igw` | Lets the public subnets reach the internet |
| Public subnets 10.0.0.0/24, 10.0.2.0/24 | `nimbus-public-a`, `nimbus-public-b` | App server (first AZ); second AZ ready for scaling |
| Private subnets 10.0.1.0/24, 10.0.3.0/24 | `nimbus-private-a`, `nimbus-private-b` | Reserved for RDS (Stage 2); **no route to the internet** |
| Route tables | `nimbus-rtb-public`, `nimbus-rtb-private` | Public: 0.0.0.0/0 → internet gateway. Private: local only (no NAT gateway, so no NAT cost) |
| Security group | `nimbus-app-sg` | Port 8501 from `AllowedWebCidr` (default anyone); SSH closed unless `AllowedSshCidr` is set |
| EC2 instance (t2.micro, Amazon Linux 2023) | `nimbus-app` | Clones the repo, installs `requirements.txt` in a venv, runs Nimbus as the `nimbus` systemd service |

**How "complete" is decided:** the instance signals CloudFormation (`cfn-signal`) only after Nimbus answers its health check (`/_stcore/health`). If installation fails, it signals failure with the reason, and the stack shows `CREATE_FAILED`. So `CREATE_COMPLETE` means the app is actually running.

## Stage 1: deploy

1. **Push first.** EC2 clones from GitHub, not from your laptop. Check that the branch you deploy is on GitHub.
2. Start the Sandbox, wait for the green dot, and open the AWS console. Check the region is **N. Virginia**.
3. Go to **CloudFormation → Create stack → With new resources (standard) → Upload a template file**, and choose `scripts/nimbus-stack.yaml`.
4. Stack name: `nimbus`. Parameters:
   - `GitBranch`: `main`, or `feature/unified-nimbus-prototype` until it is merged.
   - Leave the others at their defaults.
5. Click **Next** twice, then **Submit**. It takes about 5–10 minutes, mostly installing Python packages.

## Stage 1: evidence to capture

Crop out the account ID in every screenshot.

1. **Stack → Events**: `AppServer` with status reason *Nimbus is running on port 8501*, and the stack at `CREATE_COMPLETE`.
2. **Stack → Outputs**: `NimbusUrl`.
3. **Browser at `NimbusUrl`** (http, not https):
   - Generate `AAPL, MSFT`, showing the comparison, chart and news. This proves live data access from AWS.
   - Save a briefing, then reopen it from History.
4. **Persistence:** go to **EC2 → nimbus-app → Instance state → Reboot**. After about a minute, reload the page. Nimbus is back (systemd), and the saved briefing still opens from History (EBS root volume).
5. **EC2 → Security groups → nimbus-app-sg → Inbound rules**: 8501 open, 22 limited to 127.0.0.1/32.
6. **VPC → Route tables → nimbus-rtb-private → Routes**: only the `local` route (no internet path).

## Troubleshooting

| Symptom | Check |
|---|---|
| `CREATE_FAILED` on `AppServer` | Read the status reason in **Events**. Then **EC2 → nimbus-app → Actions → Monitor and troubleshoot → Get system log** and look for lines after `nimbus-setup` / `fatal` / `ERROR`. |
| `Remote branch … not found` | The `GitBranch` parameter does not exist on GitHub; push it or use `main`. |
| Page does not load | Use `http://`, not `https://`; check the `nimbus-app-sg` inbound rule for 8501. |
| Timed out after 20 minutes | The instance could not install packages; check the system log for pip errors. |

## Clean up after testing

**CloudFormation → nimbus → Delete.** This removes every resource listed above, including the instance's disk and any briefings saved on it. Nothing else needs deleting. Ending the Sandbox session stops the instance but does not delete the stack.

## Design choices to be able to explain

- **No NAT gateway:** the private subnets only ever hold the database, which needs no internet access. This also avoids the NAT gateway's hourly cost.
- **SSH closed by default:** troubleshooting uses the EC2 system log (as in Lesson 7). SSH can be opened to a single IP with `AllowedSshCidr`.
- **systemd instead of `nohup`:** the app restarts if it crashes and starts again after a reboot.
- **Health-checked creation:** a green stack means a working app, not just a running server.
- **Storage:** briefing files live on the instance's EBS root volume (Lesson 7 design). They survive reboots, but not deleting the stack.
