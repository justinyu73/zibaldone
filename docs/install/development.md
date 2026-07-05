# Development installation

The canonical CI environment uses Python 3.12 and Node 22. The Tauri crate has
a minimum Rust version of 1.77.2; use a current stable Rust toolchain for local
desktop builds.

## Clean clone prerequisites

- Git
- Python 3.12 with `venv` and `pip`
- Node 22 and npm 10
- Rust stable and Cargo
- FFmpeg/ffprobe for media checks and E2E audio fixtures
- Linux desktop libraries required by Tauri/WebKit when building on Linux

## Backend

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run_tests.sh
```

`backend/.env.example` contains placeholders only. Prefer the app Settings UI
for provider keys; do not commit a populated `.env`.

## Frontend

```bash
cd frontend
npm ci
npm test
npm run build
```

## E2E

```bash
cd frontend
npx playwright install chromium
npx playwright test
```

E2E tests create throwaway vaults under the OS temporary directory. They must
not point at a real note vault or make provider calls.

## Desktop development

On WSL/Linux:

```bash
cd frontend
npm run tauri:dev:wsl
```

Release artifacts for Windows and macOS are built on their native GitHub-hosted
runners. A successful source build does not replace target-machine install,
upgrade, input-method, and file-picker acceptance.

## Optional large runtimes

WhisperX, Torch, OCR runtimes, and local model files are optional and are not
part of the standard dependency install. Follow the comments in
`backend/requirements.txt` and `backend/setup_asr_runtime.sh` only when testing
those routes. They can add gigabytes to the local development environment but
must not enter Git or the standard release bundle.
