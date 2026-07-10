import { useEffect, useState } from 'react'
import { Clapperboard, FileAudio, Globe } from 'lucide-react'
import MeetingAudioView from '../meetings/MeetingAudioView'
import SourceGlyph from '../../components/SourceGlyph'
import VideoCapture from './VideoCapture'
import ArticleCapture from './ArticleCapture'

const LANES = {
  url: { type: 'video', title: '影片網址', desc: 'YouTube 字幕 → 學習筆記' },
  article: { type: 'article', title: '文章網址', desc: '網頁文章 → 重點筆記' },
  audio: { type: 'audio', title: '會議筆記音檔', desc: '現有音檔 / 逐字稿 → 批次會議筆記' },
}

// 收錄 tab：影片網址與本機音檔是同一件事（把來源變筆記）的兩個 lane。
export default function CaptureWorkspace({ settings, adopt = { url: '', kind: 'article' } }) {
  const [lane, setLane] = useState('url')
  useEffect(() => { if (adopt.url) setLane(adopt.kind === 'video' ? 'url' : 'article') }, [adopt])
  const active = LANES[lane]
  return (
    <div className="ingest-tab">
      <div className="ingest-lanes">
        <div className="tabs-mini" role="group" aria-label="收錄來源型態">
          <button className={lane === 'url' ? 'active' : ''} aria-pressed={lane === 'url'} onClick={() => setLane('url')}><Clapperboard size={14} />影片網址</button>
          <button className={lane === 'article' ? 'active' : ''} aria-pressed={lane === 'article'} onClick={() => setLane('article')}><Globe size={14} />文章網址</button>
          <button className={lane === 'audio' ? 'active' : ''} aria-pressed={lane === 'audio'} onClick={() => setLane('audio')}><FileAudio size={14} />會議筆記音檔</button>
        </div>
      </div>
      <div className="capture-banner">
        <SourceGlyph type={active.type} className="capture-banner-ic" />
        <div><div className="capture-banner-title">{active.title}</div><div className="capture-banner-desc">{active.desc}</div></div>
      </div>
      {/* all lanes stay mounted so in-progress work survives switching */}
      <div style={{ display: lane === 'url' ? 'block' : 'none' }}><VideoCapture settings={settings} adoptUrl={adopt.kind === 'video' ? adopt.url : ''} /></div>
      <div style={{ display: lane === 'article' ? 'block' : 'none' }}><ArticleCapture settings={settings} adoptUrl={adopt.kind === 'article' ? adopt.url : ''} /></div>
      <div style={{ display: lane === 'audio' ? 'block' : 'none' }}><MeetingAudioView settings={settings} /></div>
    </div>
  )
}
