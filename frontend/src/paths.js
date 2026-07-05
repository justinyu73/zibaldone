// The app runs in WSL but Obsidian is Windows-native, so let users paste a
// Windows path (C:\Users\jy\Vault) and store the WSL mount path the backend can write.
export function toWslPath(p) {
  const s = (p || '').trim()
  const m = /^([A-Za-z]):[\\/](.*)$/.exec(s)
  return m ? `/mnt/${m[1].toLowerCase()}/${m[2].replace(/\\/g, '/')}` : s
}

// Vault-root model: one root (e.g. .../notes-vault/note_study), everything else
// derived — convention over per-path configuration.
export function deriveVaultPaths(vaultRoot) {
  const root = toWslPath(vaultRoot).replace(/\/+$/, '')
  if (!root) return { root: '', youtube: '', meetings: '', articles: '', sourcesRoot: '' }
  return {
    root,
    youtube: `${root}/02_Sources/youtube`,
    meetings: `${root}/02_Sources/meetings`,
    articles: `${root}/02_Sources/articles`,
    sourcesRoot: `${root}/02_Sources`,
  }
}

// v2 settings stored a single notesFolder; recover the vault root only when the
// folder follows the convention — never guess otherwise.
export function vaultRootFromNotesFolder(notesFolder) {
  const folder = toWslPath(notesFolder).replace(/\/+$/, '')
  const m = /^(.*)\/02_Sources\/youtube$/.exec(folder)
  return m ? m[1] : ''
}
