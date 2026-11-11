import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, CustomVoice, HubVoice, Speaker, VoiceInstallJob, VoiceTune } from '../api/types'

const SAMPLE_TEXT = 'こんにちは。私の声はこんな感じです。'

/** 作るときのひな形（元の声に、高さ・速さなどの調整を重ねる） */
export const VOICE_PRESETS: { name: string; hint: string; tune: Omit<VoiceTune, 'style_id'> }[] = [
  { name: 'ふつう', hint: '元の声のまま', tune: { speed: 1, pitch: 0, intonation: 1, tempo: 1, volume: 1 } },
  { name: '子どもっぽく', hint: '高く・少し速く・元気に', tune: { speed: 1.08, pitch: 0.1, intonation: 1.3, tempo: 1.2, volume: 1 } },
  { name: '低く落ち着いて', hint: '低く・ゆっくり', tune: { speed: 0.93, pitch: -0.07, intonation: 0.9, tempo: 0.9, volume: 1 } },
  { name: 'おじいちゃん風', hint: '少し低く・ゆっくり・淡々と', tune: { speed: 0.85, pitch: -0.04, intonation: 0.7, tempo: 0.6, volume: 0.95 } },
  { name: '元気いっぱい', hint: '少し高く・速く・抑揚を大きく', tune: { speed: 1.15, pitch: 0.04, intonation: 1.5, tempo: 1.4, volume: 1.05 } },
]

const SLIDERS: { key: keyof Omit<VoiceTune, 'style_id'>; label: string; min: number; max: number; step: number; show: (v: number) => string }[] = [
  { key: 'pitch', label: '声の高さ', min: -0.15, max: 0.15, step: 0.01, show: (v) => `${v > 0 ? '+' : ''}${Math.round(v * 100)}` },
  { key: 'speed', label: '話す速さ', min: 0.5, max: 2, step: 0.05, show: (v) => v.toFixed(2) },
  { key: 'intonation', label: '感情の強さ（スタイルらしさ）', min: 0, max: 2, step: 0.1, show: (v) => v.toFixed(1) },
  { key: 'tempo', label: '話し方の緩急', min: 0, max: 2, step: 0.1, show: (v) => v.toFixed(1) },
  { key: 'volume', label: '音量', min: 0.5, max: 1.5, step: 0.05, show: (v) => v.toFixed(2) },
]

function newId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, '0')).join('')
}

interface MakerProps {
  settings: AppSettings
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void
  speakers: Speaker[]
  /** 調整した声で試しに読み上げる */
  preview: (tune: VoiceTune) => void
}

/** 声を作る: 元の声を選び、高さ・速さ・感情の強さなどを調整して名前をつけて保存する */
export function VoiceMaker({ settings, update, speakers, preview }: MakerProps) {
  const [editing, setEditing] = useState<CustomVoice | null>(null)
  const usable = speakers.filter((s) => s.acknowledged)
  const styles = usable.flatMap((s) => s.styles.map((st) => ({ id: st.id, label: `${s.name}（${st.name}）` })))
  const voices = settings.tts_custom_voices

  const start = (voice?: CustomVoice) => {
    const base = settings.tts_speaker ?? styles[0]?.id
    if (base === undefined) return
    setEditing(voice ? { ...voice } : { id: newId(), name: '', style_id: base, ...VOICE_PRESETS[0].tune })
  }

  const saveVoice = () => {
    if (!editing || !editing.name.trim()) return
    const named = { ...editing, name: editing.name.trim() }
    const exists = voices.some((v) => v.id === named.id)
    update('tts_custom_voices', exists ? voices.map((v) => (v.id === named.id ? named : v)) : [...voices, named])
    update('tts_voice', named.id)
    setEditing(null)
  }

  const remove = (id: string) => {
    update('tts_custom_voices', voices.filter((v) => v.id !== id))
    if (settings.tts_voice === id) update('tts_voice', null)
  }

  return (
    <div className="voice-maker">
      <h4>声を作る</h4>
      <p className="hint">
        元の声をもとに、高さや速さを変えて自分だけの声を作れます。作った声は上の「使う声」で選べます（「保存」を押すと保存されます）。
      </p>
      {voices.length > 0 && (
        <ul className="voice-list">
          {voices.map((v) => (
            <li key={v.id}>
              <span>
                {v.name}
                {settings.tts_voice === v.id && <span className="tag">使用中</span>}
              </span>
              <span className="row-actions">
                <button className="btn small" onClick={() => preview(v)}>
                  試聴
                </button>
                <button className="btn small" onClick={() => start(v)}>
                  直す
                </button>
                <button className="btn small danger" onClick={() => remove(v.id)}>
                  削除
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {!editing &&
        (styles.length > 0 ? (
          <button className="btn" onClick={() => start()}>
            新しい声を作る
          </button>
        ) : (
          <p className="hint">利用規約を確認した声がまだありません。上で声を選び、利用規約を確認してください。</p>
        ))}

      {editing && (
        <div className="voice-editor panel">
          <label className="field">
            <span>名前</span>
            <input
              value={editing.name}
              maxLength={20}
              placeholder="例: おじいちゃん風"
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
            />
          </label>
          <label className="field">
            <span>元の声</span>
            <select value={editing.style_id} onChange={(e) => setEditing({ ...editing, style_id: Number(e.target.value) })}>
              {styles.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.label}
                </option>
              ))}
            </select>
          </label>
          <div className="preset-row" role="group" aria-label="ひな形">
            {VOICE_PRESETS.map((p) => (
              <button key={p.name} className="btn small" title={p.hint} onClick={() => setEditing({ ...editing, ...p.tune })}>
                {p.name}
              </button>
            ))}
          </div>
          {SLIDERS.map((sl) => (
            <label className="field" key={sl.key}>
              <span>
                {sl.label}: <strong>{sl.show(editing[sl.key])}</strong>
              </span>
              <input
                type="range"
                aria-label={sl.label}
                min={sl.min}
                max={sl.max}
                step={sl.step}
                value={editing[sl.key]}
                onChange={(e) => setEditing({ ...editing, [sl.key]: Number(e.target.value) })}
              />
            </label>
          ))}
          <p className="hint">
            声の高さを大きく変えると、音質が少し落ちます（AivisSpeech の仕様）。男性・年配の声にしたいときは、下の「声を探して追加」で元になる声を追加するのがおすすめです。
          </p>
          <div className="actions">
            <button className="btn" onClick={() => preview(editing)}>
              試聴
            </button>
            <button className="btn" onClick={() => setEditing(null)}>
              やめる
            </button>
            <button className="btn primary" disabled={!editing.name.trim()} onClick={saveVoice}>
              この声を使う
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const TIMBRE_FILTERS: { id: string | null; label: string }[] = [
  { id: null, label: 'すべて' },
  { id: 'YouthfulMale', label: '若い男性' },
  { id: 'AdultMale', label: '大人の男性' },
  { id: 'MiddleAgedMale', label: 'おじさん' },
  { id: 'ElderlyMale', label: 'おじいちゃん' },
  { id: 'YoungMale', label: '男の子' },
  { id: 'YoungFemale', label: '女の子' },
  { id: 'YouthfulFemale', label: '若い女性' },
  { id: 'AdultFemale', label: '大人の女性' },
  { id: 'Neutral', label: '中性的' },
  { id: 'Mechanical', label: '機械っぽい' },
]

function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1024 / 1024)}MB`
}

/** 声を探して追加: AivisHub の公開されている声を、種類で絞り込んで試聴・追加する */
export function VoiceShop({ onChanged }: { onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [timbre, setTimbre] = useState<string | null>(null)
  const [voices, setVoices] = useState<HubVoice[] | null>(null)
  const [job, setJob] = useState<VoiceInstallJob | null>(null)
  const [confirming, setConfirming] = useState<HubVoice | null>(null)
  const [removing, setRemoving] = useState<HubVoice | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const load = useCallback(async (filter: string | null) => {
    setLoading(true)
    setError('')
    try {
      const [hub, installed] = await Promise.all([api.hubVoices(filter), api.installedVoices()])
      setVoices(hub.voices)
      setJob(installed.job)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void load(timbre)
  }, [open, timbre, load])

  // 追加中は進み具合を確認する
  useEffect(() => {
    if (job?.state !== 'installing') return
    const id = window.setInterval(async () => {
      try {
        const next = (await api.installedVoices()).job
        setJob(next)
        if (next?.state !== 'installing') {
          onChanged()
          void load(timbre)
        }
      } catch {
        /* 次の確認で再試行する */
      }
    }, 3000)
    return () => window.clearInterval(id)
  }, [job?.state, load, timbre, onChanged])

  useEffect(() => () => audioRef.current?.pause(), [])

  const play = (voice: HubVoice) => {
    audioRef.current?.pause()
    audioRef.current = new Audio(api.hubSampleUrl(voice.aivm_uuid, 0))
    audioRef.current.play().catch(() => setError('試聴の音声を再生できませんでした。'))
  }

  const install = async (voice: HubVoice) => {
    setConfirming(null)
    setError('')
    try {
      setJob((await api.installVoice(voice.aivm_uuid)).job)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const uninstall = async (voice: HubVoice) => {
    setRemoving(null)
    setError('')
    try {
      await api.uninstallVoice(voice.aivm_uuid)
      onChanged()
      await load(timbre)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (!open) {
    return (
      <div className="voice-shop">
        <h4>声を探して追加</h4>
        <p className="hint">
          男性・おじさん・おじいちゃんなど、AivisHub（AivisSpeech の声の公開サイト）で公開されている声を追加できます。一覧を開くと AivisHub に接続します（会話の内容は送りません）。
        </p>
        <button className="btn" onClick={() => setOpen(true)}>
          声の一覧を開く
        </button>
      </div>
    )
  }

  const busy = job?.state === 'installing'
  return (
    <div className="voice-shop">
      <h4>声を探して追加</h4>
      <div className="chip-row" role="group" aria-label="声の種類">
        {TIMBRE_FILTERS.map((t) => (
          <button
            key={t.label}
            className={`chip${timbre === t.id ? ' active' : ''}`}
            aria-pressed={timbre === t.id}
            onClick={() => setTimbre(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {busy && (
        <p className="hint" role="status">
          「{job.name}」を追加しています…（数分かかります。この画面を閉じても続きます）
        </p>
      )}
      {job?.state === 'done' && <p className="ok-text">「{job.name}」を追加しました。上の「使う声」で選べます（最初に利用規約の確認が必要です）。</p>}
      {job?.state === 'error' && <p className="error-text">{job.error}</p>}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {loading && <p className="hint">読み込み中…</p>}
      {voices && voices.length === 0 && !loading && <p className="hint">この種類の声は、まだ公開されていません。</p>}
      <ul className="hub-list">
        {voices?.map((v) => (
          <li key={v.aivm_uuid} className="hub-voice">
            <div>
              <strong>{v.name}</strong> <span className="tag">{v.timbre_label}</span>
              {v.installed && <span className="tag ok">追加済み</span>}
              <div className="hint">
                作者: {v.creator || '不明'}・{megabytes(v.file_size)}・{v.license_type || 'ライセンス不明'}
                {v.styles.length > 0 && `・スタイル: ${v.styles.slice(0, 4).join('、')}`}
              </div>
              {v.description && <div className="hint">{v.description}</div>}
            </div>
            <div className="row-actions">
              {v.samples.length > 0 && (
                <button className="btn small" onClick={() => play(v)}>
                  試聴
                </button>
              )}
              {v.installed ? (
                <button className="btn small danger" onClick={() => setRemoving(v)}>
                  削除
                </button>
              ) : (
                <button className="btn small primary" disabled={busy} onClick={() => setConfirming(v)}>
                  追加
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {confirming && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="voice-add-title">
          <div className="dialog panel">
            <h2 id="voice-add-title">「{confirming.name}」を追加</h2>
            <dl className="summary compact">
              <div>
                <dt>容量</dt>
                <dd>約 {megabytes(confirming.file_size)}</dd>
              </div>
              <div>
                <dt>入手元</dt>
                <dd>AivisHub（作者: {confirming.creator || '不明'}）</dd>
              </div>
              <div>
                <dt>ライセンス</dt>
                <dd>{confirming.license_type || '不明'}</dd>
              </div>
              <div>
                <dt>保存先</dt>
                <dd>AivisSpeech（AivisSpeech がダウンロードします）</dd>
              </div>
            </dl>
            <p className="hint">追加したあと、使う前にこの声の利用規約を確認してください。</p>
            <div className="actions">
              <button className="btn" onClick={() => setConfirming(null)}>
                キャンセル
              </button>
              <button className="btn primary" onClick={() => void install(confirming)}>
                ダウンロードして追加
              </button>
            </div>
          </div>
        </div>
      )}
      {removing && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="voice-remove-title">
          <div className="dialog panel">
            <h2 id="voice-remove-title">「{removing.name}」を削除しますか？</h2>
            <p>この PC の AivisSpeech から声のデータを削除します。もう一度使うには、追加し直してください。</p>
            <div className="actions">
              <button className="btn" onClick={() => setRemoving(null)}>
                キャンセル
              </button>
              <button className="btn danger" onClick={() => void uninstall(removing)}>
                削除する
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export { SAMPLE_TEXT }
