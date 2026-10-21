# litellm-local-chatbot

A ChatGPT-style web chat for a single user. It runs locally on the office laptop (Windows) and talks to the on-prem LiteLLM proxy, which serves the `qwen3.8` model (Qwen3.8-27B-FP8).

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Stack: a FastAPI + SQLite (sqlite-vec) backend and a React + Vite + TypeScript frontend
- Laptop environment check: `scripts/check-env.ps1` (read-only, needs no admin rights)

## Run it (office laptop, Windows, no admin rights)

```powershell
git pull
.\scripts\run.cmd
```

The first run creates `backend\.env` from `backend\.env.example` and asks you to set `LITELLM_API_KEY` (your LiteLLM virtual key). Run it again, then open http://127.0.0.1:8000/api/health.

**The web UI** has to be built once (and again after a `git pull` that changes `frontend\`). It needs Node 22 or newer, which you have:

```powershell
.\scripts\build-ui.cmd
.\scripts\run.cmd
```

Then open **http://127.0.0.1:8000/**. You can watch the model think, stop an answer, switch Thinking off, copy code, and start a new chat. Conversations are saved automatically (left sidebar: open, rename, delete) and are still there after a reload or restart. They are stored **in plain text** in `backend\data\chat.db` on this laptop (WAL files sit next to it; a backup of the database is made in `backend\data\backups\` before an upgrade changes it), so rely on disk encryption such as BitLocker, and do not copy that folder around. Deleting a chat overwrites its data in the file. If `npm` is blocked by your web proxy, the build script explains what to ask the Nexus administrators for (an npm repository URL).

The app listens on `127.0.0.1` only, because it has no login.

**Search and export.** The box above the chat list searches titles and the text of questions and answers (not the model's thinking) and shows where it matched; letter case is ignored for plain English letters only. **Export** (top right, for a saved chat) downloads the conversation as a Markdown file. To include the model's thinking, open `http://127.0.0.1:8000/api/conversations/<id>/export?thinking=true` instead.

## Chat from the command line

With the app running in one PowerShell window, open a second one:

```powershell
.\scripts\chat.cmd "What is 17*23?"
.\scripts\chat.cmd --no-think "Say hi in three words"     # switch the model's thinking off
.\scripts\chat.cmd --hide-thinking "Explain B-trees"        # think, but do not print the thinking
.\scripts\chat.cmd -i                                       # a conversation; /new starts over, /quit leaves
```

The thinking is printed live under `[thinking]`, then the answer under `[answer]`, then a line with the token count, total time and time to first token. The model can take several seconds of thinking before the first answer word.

## Documents (in progress)

The backend can read PDF, DOCX, Markdown and text files (up to 25 MB; a PDF up to 500 pages), split them into parts and embed them through LiteLLM (`llama-nemotron-embed-1b-v2`). Documents are attached per conversation, and only attached documents are searched in that chat. Small documents are given to the model in full; larger ones are searched and the best parts are used, with `[1]`-style source labels. The web UI for attaching documents comes next; until then use the command line. To check on the laptop that reading and embedding work:

```powershell
.\scripts\upload-doc.cmd C:\path\to\file.pdf     # uploads and shows progress
.\scripts\upload-doc.cmd -List
.\scripts\upload-doc.cmd -Delete <id>
```

Ask a question about a document (it prints the `[sources]` it used):

```powershell
.\scripts\chat.cmd --doc <id> "What does this document say about X?"
```

Only the extracted text is stored (in `backend\data\chat.db`, in plain text like the chats), not the original file.

## Using the company Nexus (when the proxy blocks public PyPI)

If your web proxy refuses package downloads (`403 Unsuitable material` for `files.pythonhosted.org`), install from the company Nexus instead. `run.cmd` then uses `pip` with a hash-pinned list (`backend/requirements.lock.txt`), so every file is verified against the same hashes as the public release.

**Ask the Nexus administrators for:**

1. The **PyPI repository URL**, a proxy or group repository that ends in `/simple/`, for example `https://nexus.example.com/repository/pypi-group/simple/`. It must proxy pypi.org, because the app needs about 26 public packages.
2. A **read-only account**: a username and a Nexus user token (preferred over a password), or confirmation that anonymous read is enabled.
3. Whether a **repository firewall or quarantine** policy applies to new components, and who approves them.
4. The **company CA certificate**, if Nexus uses an internal certificate that is not already trusted by Windows.
5. For the web UI later: the **npm repository URL**, a proxy of registry.npmjs.org.

**Configure pip for your user (no admin needed):**

```powershell
python -m pip config set global.index-url "https://<user>:<token>@nexus.example.com/repository/pypi-group/simple/"
python -m pip config list     # should now show the index-url
.\scripts\run.cmd              # picks the pip route automatically
```

This writes `%APPDATA%\pip\pip.ini`, which is outside the repository. Never put the token in the repository. A token with only read access can be revoked without side effects. Use `-Installer pip` to force this route, or `-Installer uv` to force public PyPI.

### If pip says the certificate is not trusted

`A certificate chain processed, but terminated in a root certificate which is not trusted by the trust provider` means Nexus uses a certificate from a company CA that Windows does not know. Do not use `--trusted-host`, `PIP_TRUSTED_HOST`, or any setting that turns certificate checking off: that lets anyone on the network impersonate the package server.

1. Ask the Nexus administrators for the **CA certificate** (the root, plus any intermediate) in PEM / Base64 format, and for its **SHA-256 fingerprint**.
2. Save it outside the repository, for example `%USERPROFILE%\certs\company-root-ca.pem`. A PEM file starts with `-----BEGIN CERTIFICATE-----`. A binary `.cer` file can be converted with `certutil -encode in.cer out.pem`. If there is an intermediate, put both certificates in the same file, one after the other.
3. Check the fingerprint against what the administrators told you:
   ```powershell
   certutil -dump "$env:USERPROFILE\certs\company-root-ca.pem"      # compare "Cert Hash(sha256)"
   ```
4. Tell pip to trust that file, for pip only:
   ```powershell
   python -m pip config set global.cert "$env:USERPROFILE\certs\company-root-ca.pem"
   .\scripts\run.cmd
   ```

**If pip then fails with `[X509] PEM lib`**, the file is damaged. Python can see `-----BEGIN CERTIFICATE-----` but not a complete, valid certificate after it: a line is missing or cut off, a character changed, or the `-----END CERTIFICATE-----` line is missing. This usually happens when the certificate text is copied through email, chat or a web page. Get the file again as an attachment, or export it (Windows: open the certificate, Details, Copy to File, **Base-64 encoded X.509**). Check it before running pip:

```powershell
python -c "import ssl,sys; ssl.create_default_context().load_verify_locations(sys.argv[1]); print('OK')" "$env:USERPROFILE\certs\company-root-ca.pem"
(Select-String -Path "$env:USERPROFILE\certs\company-root-ca.pem" -Pattern "BEGIN CERTIFICATE").Count
(Select-String -Path "$env:USERPROFILE\certs\company-root-ca.pem" -Pattern "END CERTIFICATE").Count
```
The first command must print `OK`, and the two counts must be equal. `run.cmd` now runs this check itself before pip starts.

Adding the CA to the Windows certificate store instead would make every program you run trust it, which is broader than needed. Do that only if IT asks you to.

## Develop and test

```bash
cd backend
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q          # LiteLLM is mocked; no network or key needed
```

The frontend (React, Vite, TypeScript):

```bash
cd frontend
npm ci
npm run dev           # http://localhost:5173, forwards /api to the backend on :8000
npm run lint && npm test && npm run build
```

After changing Python dependencies, run `uv lock` and regenerate the pinned list used by the Nexus route (CI checks that it is current):

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.lock.txt
```

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

Pushes from the office laptop have sometimes worked and sometimes been refused by the proxy, so don't rely on them. Pulling always works. Don't add stray files (for example `*.stackdump`) to the report branch, and don't merge the report branch into `main`.
