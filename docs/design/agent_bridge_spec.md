# Agent Bridge v1

## Decision

Zibaldone remains the product and the user's Markdown vault remains the only
source of truth. Agent Bridge is a derived, local-only projection for the
user's coding and research agents. It is inspired by OpenWiki's progressive
disclosure and agent instruction pattern; it is not an OpenWiki runtime,
LangChain adapter, or replacement for the capture lanes.

## Scope of v1

The user explicitly triggers **產生／更新 Agent 索引** from Settings. The
backend then scans the configured vault and writes only these Zibaldone-owned
files:

```text
_zibaldone/agent-index/index.md
_zibaldone/agent-index/manifest.json
```

The generated index contains note-relative links, title, type, description,
status, dates, tags, source/category metadata, and up to twenty outgoing
Obsidian or local Markdown links per note. It does not copy note bodies into
the index.

## Boundaries

- Markdown files in the selected vault are authoritative; the projection is
  disposable and regenerable.
- The first version scans visible `.md` files only. It excludes `.obsidian`,
  `.git`, `_attachments`, `_trash`, `_zibaldone`, hidden directories, and
  symlinks that resolve outside the vault.
- The operation is on-demand only. There is no watcher, cron, CI workflow,
  connector, provider call, telemetry, or hidden cloud sync.
- A dry run never creates the output directory. A write requires an explicit
  `confirm=true` action.
- Existing files in the output location are protected unless they carry the
  Zibaldone generated marker. User-authored Markdown is never overwritten.
- The output uses relative paths and does not put the absolute vault path into
  the generated files.
- The scan is metadata-only; full note content remains in the original vault.

## API contract

```text
GET  /api/app/agent-index/status?vault_root=<path>
POST /api/app/agent-index
```

The POST body is:

```json
{
  "vault_root": "/path/to/vault",
  "dry_run": true,
  "confirm": false
}
```

`dry_run=false` requires `confirm=true`. The response reports note count,
skipped count, truncation, output paths, and an SHA-256 of the generated
index. The operation never invokes an LLM, so its cost is zero and its result
is deterministic apart from the manifest timestamp.

## Acceptance gates

1. A dry run leaves every source note and the vault tree unchanged.
2. A confirmed run creates only the two derived files above.
3. A second run with no vault changes reports `changed=false`.
4. A foreign file at either output path is rejected rather than overwritten.
5. Generated links resolve from `_zibaldone/agent-index/index.md` back to the
   original note paths.
6. The backend test, frontend test, build, Playwright suite, and diff check
   pass before release.

## Future compatibility

OKF compatibility is an export constraint to evaluate later, not a migration
requirement. v1 deliberately keeps the output to the minimal index/manifest
projection. Any future typed-concept profile must preserve existing
frontmatter, unknown fields, user-authored templates, and note paths.
