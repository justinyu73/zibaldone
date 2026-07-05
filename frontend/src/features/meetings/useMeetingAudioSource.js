import { useEffect, useState } from 'react'
import { API, postJson } from '../../app/api'

export default function useMeetingAudioSource(audioPath) {
  const [source, setSource] = useState('')
  useEffect(() => {
    let cancelled = false
    if (!audioPath) { setSource(''); return () => { cancelled = true } }
    postJson('/app/meeting-audio-ticket', { audio_path: audioPath })
      .then((data) => {
        if (!cancelled) setSource(`${API}/app/meeting-audio?${new URLSearchParams({ audio_path: audioPath, ticket: data.ticket })}`)
      })
      .catch(() => { if (!cancelled) setSource('') })
    return () => { cancelled = true }
  }, [audioPath])
  return source
}
