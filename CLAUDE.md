# openai-job-monitor

Daily GitHub Actions job that scrapes OpenAI careers, matches against profile.json, and emails a digest. CI regenerates `config.json` from Actions secrets at runtime - never commit a real `config.json` (see `.gitignore` and `config.example.json`).

Commit autonomy: move-fast
