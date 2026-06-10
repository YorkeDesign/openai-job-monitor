# openai-job-monitor

Daily GitHub Actions job that scrapes OpenAI careers, matches against profile.json, and emails a digest. CI regenerates `config.json` from Actions secrets at runtime - never commit a real `config.json` (see `.gitignore` and `config.example.json`).

Commit autonomy: move-fast

## Follow-ups

- [ ] GitHub Support ticket #4467695 ("Clear Cached Views", filed 2026-06-10): purge of pre-rewrite commits cached by SHA after the config.json history scrub. Check https://support.github.com/tickets - resolved when `gh api repos/YorkeDesign/openai-job-monitor/commits/1002d2bc22239150d8b0e5100b376ea84318ad35` returns 404. Remove this item once confirmed.
