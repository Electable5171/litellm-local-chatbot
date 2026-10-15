# litellm-local-chatbot

A ChatGPT-style web chat for a single user. It runs locally on the office laptop (Windows) and talks to the on-prem LiteLLM proxy, which serves the `qwen3.8` model (Qwen3.8-27B-FP8).

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Stack: a FastAPI + SQLite (sqlite-vec) backend and a React + Vite + TypeScript frontend
- Laptop environment check: `scripts/check-env.ps1` (read-only, needs no admin rights)

## Branching (GitHub Flow)

- `main` is always the version that has been tested and runs on the office laptop.
- Work happens on short-lived `feature/<name>` or `fix/<name>` branches, which are merged through a PR once they work and then deleted.
- Releases that actually run on the laptop are tagged (`v0.1.0`, `v0.2.0`, …).

## Checking the laptop environment

`scripts/check-env.ps1` is read-only (it only writes one report file) and needs no admin rights. It saves a redacted report to `diagnostics/env-check-<timestamp>.txt`.

```powershell
$env:LITELLM_API_KEY = "sk-..."
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

The report hides the API key, your Windows user name and the computer name. Read it once before sharing it: it still lists the model names on the LiteLLM proxy.

To share the report, follow GitHub Flow with a short-lived branch:

```powershell
git fetch origin
git checkout -b fix/env-report origin/main
git add diagnostics\env-check-*.txt
git commit -m "chore: add laptop environment report"
git push -u origin fix/env-report
```

If the push fails with `HTTP 403` and the response has only your company proxy's `Via:` header, the proxy is blocking uploads to GitHub. Do not work around it: ask IT, and share the report text another way.
