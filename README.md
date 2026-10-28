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

**Context meter.** Above the message box, a thin bar shows how full the chat is: how many tokens the next request would use of the working budget (`CONTEXT_BUDGET_TOKENS`, 32,768 by default, minus the room kept for the answer). Hover it for the split between instructions, documents and messages. It turns amber from 75% and red when the next request would leave out older messages, and then says how many. Counting uses the same estimate as the trimming (it leans high on purpose), so it can show a little more than the model itself would count. It appears after the first answer of a saved chat and refreshes when an answer finishes, a document is attached, or the instructions change.

**Instructions.** The **Instructions** button (top right; it shows a dot when the chat has some) opens a panel where you tell the model how to behave in this chat, for example "Answer briefly". Five starter presets are included (Concise, Plain language, Step by step, Code helper, Critical reviewer); click one to load it, edit the text, and **Use in this chat**. You can save your own text as a preset, update a preset, or delete one. The text is copied into the chat, so changing or deleting a preset later does not change chats that used it, and a saved chat keeps its instructions after a reload. They apply from the next question on and cannot be changed while an answer is being written.

**Usage.** The **Usage** link at the bottom of the chat list shows what this app has stored about your answers: how many, tokens written and read, response time (average, median, slowest 5%), time to first token, thinking time, speed, a chart of answers per day and your slowest answers (click one to open that chat). Choose Today, 7 days, 30 days or All time; days follow your computer's time zone. It counts only this laptop's chats; LiteLLM's own spend log remains the source for the team's total usage.

**Edit a message.** Point at one of your messages and click **Edit**. Saving replaces that message and everything after it with a new answer to the new text. The later messages are deleted, not kept as another version, which is why the box tells you how many will go. Edit is not offered while an answer is being written, and a refused edit changes nothing.

**Titles.** A new chat is first named after your question. After the first answer is complete, the model writes a short title (thinking off, one short request, never while another answer is being written); if that fails or the model is busy, the question stays as the title. A title you typed yourself is never replaced, and chats created before this feature keep their titles. Set `AUTO_TITLES=false` in `backend\.env` to turn this off.

**Summaries of long chats.** Summarizing does not make the model's window bigger (that is fixed at 262,144 tokens, and the app works inside a smaller budget on purpose). It makes the *old part of the chat take fewer tokens of that budget*, so fewer messages get dropped. When a chat reaches 75% of the budget (`SUMMARY_TRIGGER_PERCENT`), the model writes a summary of the oldest messages after an answer finishes (thinking off, one request, never while an answer is being written, `SUMMARY_TOKENS` long). The next requests send that summary plus the newest messages (about the latest 30%, `SUMMARY_KEEP_PERCENT`) instead of the covered messages. Your chat still shows every message; the context meter says how many are replaced by a summary and lets you read it. A summary loses detail, so exact wording, numbers and code from the early part are only as good as the summary. Editing a summarized message discards the summary; regenerating the last answer keeps it. If the model is busy or answers nothing usable, nothing changes (the old behaviour of dropping the oldest messages still applies) and it is not tried again for five minutes. Set `AUTO_SUMMARY=false` in `backend\.env` to turn this off.

**Search and export.** The box above the chat list searches titles and the text of questions and answers (not the model's thinking) and shows where it matched; letter case is ignored for plain English letters only. **Export** (top right, for a saved chat) downloads the conversation as a Markdown file. To include the model's thinking, open `http://127.0.0.1:8000/api/conversations/<id>/export?thinking=true` instead.

## Run it in the background (no terminal window)

You do not have to keep a terminal open. Install once with `.\scripts\run.cmd` as above (stop it with Ctrl+C), then:

```powershell
.\scripts\start.cmd          # start in the background; does nothing if it already runs
.\scripts\status.cmd         # is it running? is LiteLLM reachable?
.\scripts\open.cmd           # start it if needed, then open the browser
.\scripts\stop.cmd
.\scripts\logs.cmd           # the end of the log (-Lines 100 for more)
.\scripts\shortcuts.cmd -Install   # start at login + a "Local Chat" desktop shortcut
.\scripts\shortcuts.cmd -Remove    # take both away again (-Status shows what is installed)
```

Closing the terminal does not stop it. The shortcuts need no admin rights and only create two files in your own Startup and Desktop folders. If the app is not running when you log in, `.\scripts\status.cmd` says so; there is no automatic restart after a crash, so run `.\scripts\start.cmd` again and look at `.\scripts\logs.cmd`. Logs are in `backend\data\logs\` (the logging is in `app.err.log`) and are moved aside when they pass 5 MB.

**Updating:** `.\scripts\stop.cmd`, `git pull`, `.\scripts\build-ui.cmd`, then `.\scripts\run.cmd -Background` (it checks the dependencies and restarts the app in the background; an older database is backed up first). Only the UI or only code changed and nothing else? `.\scripts\start.cmd -Restart` is enough.

**Security note:** the app has no login and listens on this computer only. Running it all day means anyone who can use your Windows session can use it too, so lock your screen when you leave.

**Why not Docker?** On this laptop Docker's default network (`172.17.0.0/16`) contains the LiteLLM address (`172.17.58.139`), Docker Desktop would have to be running instead of a terminal, and it needs a company licence. See the architecture document (decision 12).

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
