import { AlertTriangle, Database, FolderOpen, Library, ShieldCheck } from 'lucide-react'

const INDEX_NAME = '_youtube_index.json'

export default function StorageSettings({
  derived, draft, onOpenSetup, onPickVaultRoot, pickMessage, rootCheck,
  saved, save, setDraft, setSaved,
}) {
  return (
    <section className="panel settings-panel storage-panel">
      <div className="panel-head">
        <div><FolderOpen size={16} /><h3>筆記庫位置</h3></div>
        <span className={`state-chip ${derived.root ? 'ok' : 'info'}`}>{derived.root ? '已指定' : '後端預設'}</span>
      </div>
      <div className="settings-state neutral">
        <Database size={15} />
        <span>只填一個根目錄；影片、會議與價值庫路徑自動派生。Windows 路徑儲存時會轉為 WSL 路徑。</span>
      </div>
      <div className="row">
        <button type="button" onClick={onOpenSetup}><ShieldCheck size={14} />重新開啟首次設定</button>
      </div>
      <label><FolderOpen size={14} /> 筆記庫根目錄（vault root）
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input style={{ flex: 1 }} value={draft.vaultRoot || ''}
            onChange={(event) => { setDraft({ ...draft, vaultRoot: event.target.value }); setSaved(false) }}
            placeholder="/Users/you/Documents/notes 或貼 D:\notes" />
          <button type="button" onClick={onPickVaultRoot}><FolderOpen size={14} />選擇資料夾</button>
        </div>
      </label>
      {pickMessage && <small className="muted">{pickMessage}</small>}
      {derived.root ? (
        <div className="state-list">
          <div><span>影片筆記</span><strong>{derived.youtube}</strong></div>
          <div><span>會議筆記</span><strong>{derived.meetings}</strong></div>
          <div><span>文章筆記</span><strong>{derived.articles}</strong></div>
          <div><span>價值庫來源</span><strong>{derived.sourcesRoot}/*（自動聚合）</strong></div>
        </div>
      ) : (
        <div className="settings-note">
          <span>留空使用後端預設。索引檔：<code>{INDEX_NAME}</code>（位於影片筆記資料夾）</span>
        </div>
      )}
      {rootCheck === 'empty' && (
        <div className="settings-state info">
          <AlertTriangle size={15} />
          <span>在此根目錄下找不到 02_Sources——路徑可能少了一層或打錯（例：應為 …/note_study 或 …/macnote 這種包含 02_Sources 的資料夾）。第一次存入會自動建立資料夾，但若你已有既有筆記庫，請確認路徑指到正確層級。</span>
        </div>
      )}
      <label><Library size={14} /> 額外價值庫資料夾（選填，一行一個，併入自動聚合）
        <textarea rows={3} value={(draft.libraryFolders || []).join('\n')}
          onChange={(event) => {
            setDraft({ ...draft, libraryFolders: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })
            setSaved(false)
          }}
          placeholder={'/Users/you/other-notes/clips'} />
      </label>
      <div className="row end">
        {saved && <span className="state-chip ok">已儲存</span>}
        <button className="primary" onClick={save}>儲存設定</button>
      </div>
    </section>
  )
}
