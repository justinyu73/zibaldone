# Privacy and network behavior

## Local data

The app is local-first. Notes are Markdown files written to the folder selected
by the user. Runtime configuration and provider keys are stored in the user's
home configuration directory, outside the repository. Supported systems apply
owner-only permissions to the config file where available.

The app does not require a hosted account and does not include telemetry.

## Network actions

| Action | Network destination | Trigger |
|---|---|---|
| YouTube caption retrieval | YouTube/caption endpoints | User previews or imports a YouTube source |
| Article extraction | The URL supplied by the user | User requests article fetch |
| Cloud transcription | Selected transcription provider | User selects a cloud/paid ASR route and confirms |
| AI translation/summary | OpenAI, Anthropic, or Google | User selects a cloud model and executes the action |
| Local model inference | Loopback built-in llama.cpp (127.0.0.1) | User selects the built-in local model |
| Built-in model download | llama.cpp release + model host | First-use install of the built-in local runtime |
| Update check/download | This project's GitHub Release | User checks for or installs an update |
| Radar/news scan | Configured feeds, HN, or GitHub | User runs the radar scan |

Provider prompts may contain transcript or article text required for the
requested operation. Do not select a cloud route for material that must remain
entirely local.

## Keys and credentials

- Provider keys are optional and scoped to the provider selected by the user.
- The UI displays only masked hints after saving.
- Keys must never be included in notes, logs, screenshots, bug reports, test
  fixtures, or Git commits.
- Testing a provider key performs a small real network request and may incur a
  provider charge; it must remain an explicit user action.

## Local API boundary

The packaged webview talks to a FastAPI sidecar over loopback. A per-launch
session token protects state-changing and sensitive routes. The UI rejects
non-loopback API overrides. The app is not designed to expose its backend to a
LAN or the public internet.

## File deletion and retention

The selected note vault is external user data. Application upgrade or uninstall
must not remove it. Destructive note actions remain explicit and should preserve
the existing backup/rollback behavior where provided.
