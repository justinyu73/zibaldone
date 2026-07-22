# Agent Bridge v1 / AB-002-A

**Status:** adopted design (2026-07-20); the v1 authority and safety boundaries
remain active, while the output shape is superseded by AB-002-A. OpenWiki is a
reference for the agent-readable projection pattern,
not a replacement source, runtime, or product direction for Zibaldone. The
description of OpenWiki in this file was re-verified on 2026-07-21 and has since
widened. `ZIB-AB-002-A` below is now the active additive format decision;
`ZIB-AB-002-B` and `ZIB-AB-002-C` remain unselected.

**Authority:** detailed contract for [`ZIB-AB-001`](../architecture.md#zib-ab-001).
The architecture map is the canonical entrypoint; this file owns only the
Agent Bridge contract and acceptance gates.

## Decision

Zibaldone remains the product and the user's Markdown vault remains the only
source of truth. Agent Bridge is a derived, local-only projection for the
user's coding and research agents. It is inspired by OpenWiki's progressive
disclosure and agent instruction pattern; it is not an OpenWiki runtime,
LangChain adapter, or replacement for the capture lanes.

## Scope of v1

The user explicitly triggers **產生／更新 Agent 索引** from Settings. The
backend then scans the configured vault and writes only this Zibaldone-owned
OKF v0.1 bundle:

```text
_zibaldone/agent-index/index.md
_zibaldone/agent-index/concepts/<vault-relative-note-path>.md
```

The bundle root is the OKF `index.md`; each concept file has YAML frontmatter
with a non-empty `type`. The projection contains note-relative links, title,
type, description, status, dates, tags, source/category metadata, and up to
twenty outgoing Obsidian or local Markdown links per note. It does not copy note
bodies into the projection.

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
  During a confirmed migration, only stale Zibaldone-owned concept files and
  the old Zibaldone-owned `manifest.json` may be removed.
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
bundle-root index. The operation never invokes an LLM, so its cost is zero and
its result is deterministic.

## Acceptance gates

1. A dry run leaves every source note and the vault tree unchanged.
2. A confirmed run creates only the derived OKF bundle files above.
3. A second run with no vault changes reports `changed=false`.
4. A foreign file at any generated output path is rejected rather than
   overwritten.
5. The root index links each concept, and each generated concept links back to
   its original vault-relative note path.
6. Every generated non-reserved Markdown concept has a parseable frontmatter
   block with a non-empty `type`; the root index declares `okf_version: "0.1"`.
7. The backend test, frontend test, build, Playwright suite, and diff check
   pass before release.

## Future compatibility

The selected AB-002-A decision below makes OKF v0.1 the output format while
preserving the v1 local-only, metadata-only, disposable projection boundary.

<a id="zib-ab-002"></a>
## ZIB-AB-002 — OpenWiki / OKF comparison and v2 candidates

**Status:** `ZIB-AB-002-A` adopted (2026-07-22); B and C remain research/open.
Map entry:
[`ZIB-ARCH-001`](../architecture.md#zib-ab-002). Everything in this section is a
candidate or an open question unless explicitly marked as the active A
decision. The canonical implementation contract is below.

<a id="zib-ab-002-a"></a>
### ZIB-AB-002-A — OKF v0.1 projection

**Status:** active decision (2026-07-22). The user selected **A**. Reference:
[OKF v0.1 specification](https://okf.md/spec/).

Zibaldone adopts the OKF v0.1 bundle shape for the existing Agent Bridge
projection. The bundle remains disposable, regenerable, local-only, and
metadata-only; the vault Markdown remains authoritative. The existing API and
explicit-confirmation gate remain in force.

- `_zibaldone/agent-index/index.md` is the bundle-root index and declares
  `okf_version: "0.1"` in YAML frontmatter.
- Each source note becomes one derived file under
  `_zibaldone/agent-index/concepts/`, with a non-empty `type` derived from the
  source frontmatter. If no type is present, the projection-only fallback is
  `note`; no source note is rewritten.
- Concept files carry metadata and a link back to the vault-relative source;
  note bodies are never copied. The root index links to the concepts.
- New runs do not create `manifest.json`. A previously generated Zibaldone
  manifest is removed only during an explicit confirmed migration; a foreign
  manifest or foreign Markdown output is protected and rejects the write.
- B (activation/increment) and C (evidence-anchored concept profile) are not
  included. They require separate decisions and acceptance evidence.

### Fact correction on the v1 reference

The v1 decision characterized OpenWiki as a progressive-disclosure and agent
instruction pattern. Re-verified against the upstream project and specification
on 2026-07-21, that description is incomplete:

- OpenWiki (LangChain) is a CLI with `--init` / `--update`, running in a **code
  mode** (`openwiki/` inside a repository) or a **personal mode**
  (`~/.openwiki/wiki/`, described upstream as a local personal brain).
- Since 0.2 it emits **OKF v0.1 bundles** — the Google Cloud open specification
  published 2026-06-12. Baseline conformance is Markdown plus YAML frontmatter
  with a mandatory non-empty `type` per concept, bundle-root index files, typed
  concepts, and evidence-backed relations.
- It regenerates directory `index.md` files deterministically after each agent
  run, and writes a `logs.md` changelog so a consumer can act on what changed
  instead of re-reading the whole wiki.
- It writes `AGENTS.md` and `CLAUDE.md` at the repository root, carrying
  prompting that instructs a coding agent to consult the wiki.
- It also ships OAuth connectors (Gmail, Notion, X, web search), multi-provider
  LLM routing, and telemetry.

This is drift in how an external reference is described. It contradicts no
Zibaldone implementation, and the v1 decision — borrow the pattern, do not adopt
the runtime — still holds.

Sources: `github.com/langchain-ai/openwiki`;
`langchain.com/blog/openwiki-0-2-adds-okf-support`;
`openknowledgeformat.com/implementations/openwiki`; Google Cloud OKF
announcement.

### Where the two products actually differ

| Dimension | Zibaldone | OpenWiki 0.2 |
|---|---|---|
| Source of truth | the user's Markdown vault | the generated wiki itself |
| Intake | YouTube, article, meeting audio (3-tier ASR, captions, OCR) | codebase, API connectors |
| Claim discipline | `[mm:ss]` or the item is dropped; human review gate before a note is written | LLM judgment plus schema validation; no source-anchor requirement |
| Projection | metadata-only, zero LLM, deterministic, disposable | LLM-derived concepts and relations; determinism only for index regeneration |
| Output format | OKF v0.1 metadata-only projection | OKF v0.1 |
| Activation | none — nothing tells an agent the index exists | `AGENTS.md` / `CLAUDE.md` instruct the agent to read it |
| Increment | reports `changed` true/false only | `logs.md` per-run change list |
| Boundary | no accounts, telemetry, connectors, or watchers | OAuth connectors and telemetry present |

The differentiator OpenWiki cannot structurally reproduce is the **provenance
chain**: media → timestamp-anchored claim → human-approved note. It never holds
the audio, so it cannot emit a concept carrying a verifiable source anchor.

The remaining gap selected for later work is ours, not theirs: no agent is ever
told the projection exists. The increment/change-log layer is also unselected.

### Candidate slices

Candidates are independent; A and B are additive to v1, C is a scope change.

**A — OKF-conformant projection (adopted as `ZIB-AB-002-A`).** Emit the
projection as an OKF v0.1 bundle instead of the private index/manifest pair.
Baseline conformance requires only frontmatter with a non-empty `type` plus
bundle-root indexes, so the engineering cost is close to zero and the return is
that any OKF consumer can read the vault projection. The active contract is
defined above.
*Tradeoffs:* OKF v0.1 is one month old and will churn; `type` must be derived
from existing note frontmatter, and that derivation may exist **only** in the
projection — writing a derived `type` back into a source note would violate the
v1 boundary that the vault is authoritative and never rewritten.

**B — Activation and increment layer.** Emit an agent instruction pointer so
agents actually consult the index, plus a per-note change log so consumers can
read only what moved since the last run.
*Tradeoffs:* an instruction file at the vault root writes into user-authored
territory and must inherit the v1 generated-marker protection rule (never
overwrite a foreign file). Its acceptance is not verifiable inside Zibaldone —
the op-demo has to be external: open a coding agent in the vault, ask a
question, observe it cite the index.

**C — Evidence-anchored concept profile.** Position Zibaldone as the OKF
producer whose concepts carry verifiable source anchors: source URL, `[mm:ss]`,
ASR engine, human-reviewed flag. OKF asks relations to be evidence-backed;
Zibaldone holds literal evidence.
*Tradeoffs:* this is a positioning change, not a feature. Introducing LLM
concept synthesis would collide with both hard rules — "no timestamp, no claim"
and the human review gate — by putting unattributed derived claims next to
reviewed notes. The safe form is to project **only notes that already passed the
review gate** and keep the concept layer deterministic, but whether that is
still worth calling a concept profile is unresolved.

### Non-goals (unchanged from v1)

Connectors, OAuth, watchers, schedulers, cloud sync, and telemetry remain
excluded. They are the reason the local-first claim is honest, and
`ZIB-ARCH-001` lists them under what is deliberately absent. Adopting OpenWiki's
format is not a reason to adopt its runtime.

### Open questions

1. Should B (activation and increment) be selected separately from A?
2. Should C (evidence-anchored concept profile) be selected separately from A?
3. If B: where does the instruction pointer live so it neither collides with a
   user's own agent instruction file nor requires a watcher to stay current?
4. Does an OKF bundle change the disposability guarantee — is the projection
   still safe to delete and regenerate once external tools consume it?
5. Should the Session Hub strategy summary and handoff pointer be refreshed once
   this research closes, or only when a candidate is adopted?
