"""Standalone entrypoint for the bundled FastAPI sidecar (block #8b).

PyInstaller bundles this into a self-contained binary so the desktop shell can
start the backend without a Python install, source tree, or venv. Secrets are
NOT bundled: dotenv is disabled and the host app supplies env vars (e.g.
OPENAI_API_KEY) at launch. Host/port match the dev sidecar defaults.
"""
import os


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _sidecar_host() -> str:
    host = os.getenv("VIDEO_INTAKE_FASTAPI_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in _LOOPBACK_HOSTS and os.getenv("VIDEO_INTAKE_ALLOW_PUBLIC_BIND") != "1":
        raise SystemExit(
            f"Refusing to bind sidecar to non-loopback host {host!r}. "
            "Set VIDEO_INTAKE_ALLOW_PUBLIC_BIND=1 only for an explicitly secured deployment."
        )
    return host


def main() -> None:
    os.environ.setdefault("VIDEO_INTAKE_DISABLE_DOTENV", "1")
    host = _sidecar_host()
    port = int(os.getenv("VIDEO_INTAKE_FASTAPI_PORT", "8766"))

    import uvicorn

    from main import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
