# Troubleshooting

## Backend does not connect

1. Wait for the packaged sidecar startup check to finish.
2. Open **Settings** and choose **Check connection again**.
3. Use **Open log folder** in the version/diagnostics panel.
4. Restart the app if the sidecar exited.

Do not start a second backend on the packaged port unless diagnosing a known
development configuration.

## Note folder is missing or not writable

- Reopen first-run setup or Settings and select the vault root again.
- Confirm the folder exists and the current OS user can read/write it.
- On macOS, grant access only when the system file dialog requests it.
- On Windows, use a native drive path; the app normalizes legacy WSL paths when
  needed.

## Local ASR is unavailable

Check the local ASR readiness state in the app. Standard releases do not bundle
every optional model or WhisperX/Torch stack. Install only the runtime required
for the selected route or choose a clearly labelled cloud route.

## Cloud model fails

- Confirm the selected model belongs to the provider whose key is configured.
- Check the masked key status in Settings.
- Confirm daily and per-job cost caps have not blocked the call.
- Use **Test key** only when a small real provider request is acceptable.

## Update fails

- Confirm GitHub is reachable.
- Keep the current app installed; a failed update should restart its sidecar.
- Open the log folder and inspect the updater error.
- Download the newer installer/DMG manually from GitHub Releases when needed.

## SmartScreen or Gatekeeper warning

The updater signature verifies project release integrity but is not Windows
Authenticode or Apple notarization. Follow the narrow platform instructions in
`docs/install/windows.md` or `docs/install/macos.md`, and only for files obtained
from this project's GitHub Release.

## Reporting diagnostics

Never attach API keys, complete private transcripts, personal notes, or the app
config file. Prefer the app log, version, OS, failing action, and a minimal
redacted reproduction.
