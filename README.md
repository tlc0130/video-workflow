# Video Workflow Automation

This repository contains a fully-automated starter workflow for creating short-form videos and publishing them to **YouTube Shorts** and **TikTok**.

## What this does

The workflow is designed to run unattended on a schedule:

1. Generate a topic/script (or use a static prompt).
2. Generate voice-over audio from script text.
3. Build a short 9:16 video with captions using FFmpeg.
4. Upload to YouTube Shorts.
5. Upload to TikTok using the TikTok Content Posting API.

> ⚠️ Complete automation is possible, but both platforms require app approval, OAuth setup, and policy compliance. TikTok in particular may require a Business account and approved scopes.

## Architecture

- `src/workflow.py`: end-to-end CLI pipeline.
- `config.example.json`: environment-agnostic config template.
- `requirements.txt`: Python dependencies.

## Quick start

### 1) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Install FFmpeg

Linux:

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

macOS:

```bash
brew install ffmpeg
```

### 3) Configure secrets

Copy and edit config:

```bash
cp config.example.json config.json
```

Set values for:

- OpenAI API key (for script generation).
- Google OAuth credentials and refresh token (YouTube).
- TikTok access token.

### 4) Run once

```bash
python -m src.workflow --config config.json --run-once --dry-run
```

### 5) Schedule automation

Use cron or GitHub Actions to run on a schedule.

Example cron (every day at 14:00 UTC):

```cron
0 14 * * * /path/to/repo/.venv/bin/python -m src.workflow --config /path/to/repo/config.json --run-once >> /path/to/repo/workflow.log 2>&1
```

## Notes on "completely automated"

To keep this fully automated in production:

- Use refresh-token-based auth flows for YouTube.
- Keep TikTok token rotation automated if your app requires expiring tokens.
- Store secrets in a secret manager (GitHub Secrets, AWS Secrets Manager, 1Password CLI, etc.).
- Add retry logic + alerting (Slack/email) for failed runs.
- Use an editorial safety filter before publishing.

## Legal/compliance checklist

- Confirm you have rights to all media assets.
- Follow YouTube API Services Terms.
- Follow TikTok Developer Terms and content policies.
- Label AI-generated content where required by platform policy or local law.


## What to do next (practical launch checklist)

If your question is "what do I do from here?", do these in order:

1. **Get API access approved**
   - YouTube Data API v3 project + OAuth client + refresh token with `youtube.upload` scope.
   - TikTok developer app approved for content posting scopes required by your account type.
2. **Create a private test channel/account pair**
   - Use non-production YouTube and TikTok accounts for first tests.
3. **Copy `config.example.json` to `config.json` and fill all placeholders.**
4. **Install FFmpeg and Python dependencies.**
5. **Run one local test**
   - `python -m src.workflow --config config.json --run-once --dry-run`
6. **Verify output manually**
   - Check generated video quality, caption timing, title/description, and policy compliance.
7. **Enable one platform first**
   - Set one of `youtube.enabled`/`tiktok.enabled` to `false` while stabilizing the other.
8. **Add monitoring**
   - At minimum, email/Slack alerts on non-zero exits.
9. **Schedule runs**
   - Start with 1 run/day; increase after observing stability for 7+ days.
10. **Harden before scaling**
   - Rotate secrets, add retries/backoff, add idempotency to avoid duplicate uploads.

### Recommended first successful milestone

- Day 1: Automatically generate + upload exactly **1 private/unlisted YouTube Short**.
- Day 2: Add TikTok publish flow.
- Day 3: Put both on a daily schedule with alerts.

This phased rollout avoids burning API quotas and reduces account-risk from accidental spam-like behavior.


## Testing and CI

Run tests locally:

```bash
pip install -r requirements-dev.txt
pytest -q
```

A GitHub Actions workflow is included at `.github/workflows/ci.yml` and runs tests on every push and pull request.

## Recommended additions now included

The workflow now includes:

- **Config validation**: fails fast when required keys are missing.
- **Dry-run mode**: generate script/video without uploading (`--dry-run`).
- **Upload retries**: transient TikTok upload errors are retried with backoff-like delay.

When you are ready to publish for real, run without `--dry-run`.

