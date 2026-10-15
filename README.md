# litellm-local-chatbot

A ChatGPT-style web chat for a single user that runs on a local laptop and talks to an existing LiteLLM proxy (model: `Qwen/Qwen3.8-27B-FP8`).

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Stack: FastAPI + SQLite (sqlite-vec) backend, React + Vite + TypeScript frontend

## Branching (GitHub Flow)

- `main` is always the version that has been tested and runs on the office laptop.
- Work happens on short-lived `feature/<name>` or `fix/<name>` branches. Each branch is merged through a PR once it works, then deleted.
- Releases that actually run on the laptop are tagged (`v0.1.0`, `v0.2.0`, …).
