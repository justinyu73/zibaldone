import { describe, it, expect } from 'vitest'
import { deriveVaultPaths, toWslPath, vaultRootFromNotesFolder } from './paths'

describe('toWslPath', () => {
  it('converts a Windows path to the WSL mount path', () => {
    expect(toWslPath('C:\\Users\\jy\\Vault\\YouTube')).toBe('/mnt/c/Users/jy/Vault/YouTube')
  })

  it('lowercases the drive letter', () => {
    expect(toWslPath('D:\\repos\\vault')).toBe('/mnt/d/repos/vault')
  })

  it('handles mixed slashes', () => {
    expect(toWslPath('C:\\Users\\jy/Vault')).toBe('/mnt/c/Users/jy/Vault')
  })

  it('leaves a WSL/POSIX path untouched', () => {
    expect(toWslPath('/mnt/c/Users/jy/Vault')).toBe('/mnt/c/Users/jy/Vault')
    expect(toWslPath('/home/user/vault')).toBe('/home/user/vault')
  })

  it('trims surrounding whitespace', () => {
    expect(toWslPath('  C:\\Vault  ')).toBe('/mnt/c/Vault')
  })

  it('returns empty for empty input', () => {
    expect(toWslPath('')).toBe('')
    expect(toWslPath(null)).toBe('')
  })
})

describe('deriveVaultPaths', () => {
  it('derives youtube/meetings/sources from the vault root', () => {
    const p = deriveVaultPaths('/mnt/d/repos/vault-notes')
    expect(p.youtube).toBe('/mnt/d/repos/vault-notes/02_Sources/youtube')
    expect(p.meetings).toBe('/mnt/d/repos/vault-notes/02_Sources/meetings')
    expect(p.articles).toBe('/mnt/d/repos/vault-notes/02_Sources/articles')
    expect(p.sourcesRoot).toBe('/mnt/d/repos/vault-notes/02_Sources')
  })

  it('normalizes Windows paths and trailing slashes', () => {
    const p = deriveVaultPaths('C:\\Users\\jy\\notes\\note_study\\')
    expect(p.root).toBe('/mnt/c/Users/jy/notes/note_study')
    expect(p.youtube).toBe('/mnt/c/Users/jy/notes/note_study/02_Sources/youtube')
  })

  it('returns empties for no root', () => {
    expect(deriveVaultPaths('')).toEqual({ root: '', youtube: '', meetings: '', articles: '', sourcesRoot: '' })
  })
})

describe('vaultRootFromNotesFolder (v2 settings migration)', () => {
  it('recovers the root from a conventional youtube folder', () => {
    expect(vaultRootFromNotesFolder('/mnt/d/repos/vault-notes/02_Sources/youtube'))
      .toBe('/mnt/d/repos/vault-notes')
    expect(vaultRootFromNotesFolder('C:\\notes\\note_study\\02_Sources\\youtube'))
      .toBe('/mnt/c/notes/note_study')
  })

  it('refuses to guess from non-conventional folders', () => {
    expect(vaultRootFromNotesFolder('/home/user/some/random/folder')).toBe('')
    expect(vaultRootFromNotesFolder('')).toBe('')
  })
})
