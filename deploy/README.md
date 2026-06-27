# Deployment — AWS (Mumbai / ap-south-1)

This service runs on a single EC2 instance, provisioned with Terraform, fronted
by Caddy (auto-HTTPS), with logs/metrics in CloudWatch and CI/CD via GitHub
Actions.

```
GitHub push ──► Actions (SSH) ──► EC2 (Ubuntu 22.04, t3.medium)
                                    ├─ systemd: todozee.service (uvicorn :5016)
                                    ├─ Caddy   :443 ──► 127.0.0.1:5016  (HTTPS)
                                    └─ CloudWatch agent ──► logs + mem/disk metrics
```

## Live endpoints
- HTTPS: `https://frames.chatbucket.chat` (after DNS points at the Elastic IP)
- Health: `GET /`  · Frames: `GET /frames`  · Process: `POST /process`
- Logs (no SSH): `GET /logs?lines=200`

## Infrastructure
Terraform lives **outside this repo** (it holds state + the SSH private key) at
`todozee-infra/`. Resources: EC2 + Elastic IP, security group (22/80/443),
IAM role (CloudWatch + SSM), CloudWatch log group, SNS email alerts, and alarms
for CPU, status-check, memory, disk, and app ERROR log lines.

## One-time setup after `terraform apply`

### 1. DNS
Create an **A record**: `frames.chatbucket.chat` → `<elastic_ip>` (see Terraform
output `elastic_ip`). Caddy issues the TLS cert automatically once it resolves.

### 2. GitHub Actions secrets
Add three repo secrets (Settings → Secrets and variables → Actions):

| Secret        | Value                                              |
|---------------|----------------------------------------------------|
| `EC2_HOST`    | the Elastic IP                                     |
| `EC2_USER`    | `ubuntu`                                            |
| `EC2_SSH_KEY` | full contents of `todozee-infra/todozee-frames-key.pem` |

Or with the `gh` CLI from the repo root:
```bash
gh secret set EC2_HOST    --body "<elastic_ip>"
gh secret set EC2_USER    --body "ubuntu"
gh secret set EC2_SSH_KEY < ../todozee-infra/todozee-frames-key.pem
```

## CI/CD
`.github/workflows/deploy.yml` runs on every push to `main` (or manual
dispatch). It SSHes in, `git reset --hard origin/main`, rebuilds `frames/`,
`pip install -r requirements.txt`, restarts the service, and health-checks it.

## Frame assets
The app reads `frames/<id>_01.png` (per `frames_metadata/frames.json`) but the
repo ships `original_frames/<bare>.png`. `deploy/build_frames.sh` maps/copies
them; it runs on boot and on every deploy. Keep the two in sync if you add
frames.

## Manual ops (SSH)
```bash
ssh -i todozee-infra/todozee-frames-key.pem ubuntu@<elastic_ip>
sudo systemctl status todozee        # service state
sudo journalctl -u todozee -f        # live app logs
sudo systemctl restart todozee       # restart
sudo systemctl reload caddy          # reload proxy/cert config
```
