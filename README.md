# litellm-local-chatbot

A ChatGPT-style web chat for a single user. It runs locally on the office laptop (Windows) and talks to the on-prem LiteLLM proxy, which serves the `Qwen/Qwen3.8-27B-FP8` model.

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Stack: a FastAPI + SQLite (sqlite-vec) backend and a React + Vite + TypeScript frontend
- Laptop environment check: `scripts/check-env.ps1` (read-only, needs no admin rights)

## Branching (GitHub Flow)

- `main` is always the version that has been tested and runs on the office laptop.
- Work happens on short-lived `feature/<name>` or `fix/<name>` branches, which are merged through a PR once they work and then deleted.
- Releases that actually run on the laptop are tagged (`v0.1.0`, `v0.2.0`, …).
