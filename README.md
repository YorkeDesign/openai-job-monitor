# openai-job-monitor
Daily OpenAI job monitoring for San Francisco roles

## Tech Stack

- **Language / runtime:** Python 3.9 (stdlib + `requests`, `schedule`).
- **Data source:** OpenAI careers via the Ashby public job-board API (no key required).
- **CV / job matching:** Anthropic Claude API (`claude-3-5-sonnet`) scores each role against a profile. Requires `ANTHROPIC_API_KEY`.
- **Notifications:** Gmail SMTP for the daily digest email (with CSV attachment).
- **Frontend:** static `Index.html` dashboard served via GitHub Pages (custom domain via `CNAME`).
- **Hosting / scheduling:** GitHub Actions cron (daily ~9 AM NZDT) runs the monitor; no server.
- **Storage:** flat JSON/CSV files under `job_data/` committed back to the repo.

### Paid services

- **Anthropic API** - Claude 3.5 Sonnet for the optional CV-matching pass (metered per token). Everything else (Ashby API, Gmail SMTP, GitHub Actions/Pages) is free.
