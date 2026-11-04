import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, Speaker, SpeakersResponse, SttStatus } from '../api/types'
import { SpeechPlayer } from '../audio/SpeechPlayer'

interface Props {
  settings: AppSettings
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void
}

const SAMPLE_TEXT = 'こんにちは。私の声はこんな感じです。'

/** 音声認識・読み上げの設定（設定画面の一部。値の保存は設定画面の「保存」で行う） */
export function VoiceSettings({ settings, update }: Props) {
  return (
    <>
      <SttSettings settings={settings} update={update} />
      <TtsSettings settings={settings} update={update} />
    </>
  )
}

function SttSettings({ settings, update }: Props) {
  const [status, setStatus] = useState<SttStatus | null>(null)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await api.sttStatus())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // ダウンロード中は進捗を定期的に確認する
  useEffect(() => {
    if (status?.download?.state !== 'downloading') return
    const id = window.setInterval(() => void load(), 2000)
    return () => window.clearInterval(id)
  }, [status?.download?.state, load])

  const start = async (model: string) => {
    setConfirming(null)
    try {
      await api.downloadWhisper(model)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const selected = status?.models.find((m) => m.name === settings.stt_model)
  const job = status?.download
  const target = confirming ? status?.models.find((m) => m.name === confirming) : null

  return (
    <>
      <h3>音声認識（faster-whisper）</h3>
      <label className="field">
        <span>認識モデル</span>
        <select value={settings.stt_model} onChange={(e) => update('stt_model', e.target.value)}>
          {(status?.models ?? [{ name: settings.stt_model, size_gb: 0, description: '', recommended: false, installed: false }]).map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}（約{m.size_gb}GB・{m.description}）{m.installed ? '' : ' - 未ダウンロード'}
            </option>
          ))}
        </select>
      </label>
      {selected && !selected.installed && job?.state !== 'downloading' && (
        <p className="warn-text">
          このモデルはまだダウンロードされていません。
          <button className="btn small" onClick={() => setConfirming(selected.name)}>
            ダウンロード（約{selected.size_gb}GB）
          </button>
        </p>
      )}
      {job?.state === 'downloading' && (
        <p className="hint" role="status">
          「{job.model}」をダウンロード中… {job.downloaded_gb}GB
        </p>
      )}
      {job?.state === 'error' && <p className="error-text">{job.error}</p>}
      {job?.state === 'done' && <p className="ok-text">「{job.model}」のダウンロードが完了しました。</p>}
      <label className="field">
        <span>処理装置</span>
        <select value={settings.stt_device} onChange={(e) => update('stt_device', e.target.value as 'cpu' | 'cuda')}>
          <option value="cpu">CPU（推奨。GPUメモリを会話AIに使うため）</option>
          <option value="cuda">GPU（高速。CUDAライブラリが必要。使えない場合はCPUで処理）</option>
        </select>
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={settings.stt_auto_send} onChange={(e) => update('stt_auto_send', e.target.checked)} />
        認識したらすぐに送信する（オフにすると、認識結果を確認・修正してから送信）
      </label>
      {error && <p className="error-text">{error}</p>}

      {target && status && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="stt-dl-title">
          <div className="dialog panel">
            <h2 id="stt-dl-title">音声認識モデルのダウンロード</h2>
            <dl className="summary compact">
              <div>
                <dt>モデル</dt>
                <dd>{target.name}</dd>
              </div>
              <div>
                <dt>容量（目安）</dt>
                <dd>約 {target.size_gb} GB</dd>
              </div>
              <div>
                <dt>保存先</dt>
                <dd className="path">{status.models_dir}</dd>
              </div>
              <div>
                <dt>入手元</dt>
                <dd>Hugging Face</dd>
              </div>
            </dl>
            <div className="actions">
              <button className="btn" onClick={() => setConfirming(null)}>
                キャンセル
              </button>
              <button className="btn primary" onClick={() => void start(target.name)}>
                ダウンロードする
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function TtsSettings({ settings, update }: Props) {
  const [data, setData] = useState<SpeakersResponse | null>(null)
  const [error, setError] = useState('')
  const [policy, setPolicy] = useState<{ speaker: Speaker; text: string } | null>(null)
  const playerRef = useRef<SpeechPlayer | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await api.speakers())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
    return () => playerRef.current?.dispose()
  }, [load])

  const current = data?.speakers.find((s) => s.styles.some((st) => st.id === settings.tts_speaker))

  const showPolicy = async (speaker: Speaker) => {
    setError('')
    try {
      setPolicy({ speaker, text: (await api.speakerPolicy(speaker.speaker_uuid)).policy })
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const acknowledge = async () => {
    if (!policy) return
    try {
      await api.acknowledgeSpeaker(policy.speaker.speaker_uuid)
      setPolicy(null)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const preview = () => {
    if (settings.tts_speaker == null) return
    setError('')
    if (!playerRef.current) {
      playerRef.current = new SpeechPlayer()
      playerRef.current.onError = setError
    }
    playerRef.current.stop()
    playerRef.current.unlock()
    playerRef.current.enqueue(SAMPLE_TEXT, settings.tts_speaker)
  }

  return (
    <>
      <h3>読み上げ（AivisSpeech）</h3>
      {data && !data.available ? (
        <div className="banner warn" role="status">
          {data.message}
          <button className="btn small" onClick={() => void load()}>
            再確認
          </button>
        </div>
      ) : (
        <>
          <label className="field">
            <span>声</span>
            <select
              value={settings.tts_speaker ?? ''}
              onChange={(e) => update('tts_speaker', e.target.value === '' ? null : Number(e.target.value))}
            >
              <option value="">選択してください</option>
              {data?.speakers.map((s) =>
                s.styles.map((st) => (
                  <option key={st.id} value={st.id}>
                    {s.name}（{st.name}）{s.acknowledged ? '' : ' - 利用規約 未確認'}
                  </option>
                )),
              )}
            </select>
          </label>
          {current && !current.acknowledged && (
            <p className="warn-text">
              この声を使うには、利用規約の確認が必要です。
              <button className="btn small" onClick={() => void showPolicy(current)}>
                利用規約を確認
              </button>
            </p>
          )}
          {current?.acknowledged && (
            <p className="hint">
              利用規約 確認済み
              <button className="btn small" onClick={() => void showPolicy(current)}>
                再表示
              </button>
              <button className="btn small" onClick={preview} title="設定の保存前は、話速は保存済みの値で再生されます">
                試聴
              </button>
            </p>
          )}
        </>
      )}
      <label className="field">
        <span>
          話す速さ: <strong>{settings.tts_speed.toFixed(1)}</strong>
        </span>
        <input
          type="range"
          min={0.5}
          max={2}
          step={0.1}
          value={settings.tts_speed}
          onChange={(e) => update('tts_speed', Number(e.target.value))}
        />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={settings.tts_auto_read} onChange={(e) => update('tts_auto_read', e.target.checked)} />
        音声会話でAIの返答を自動で読み上げる
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.tts_engine_autostart}
          onChange={(e) => update('tts_engine_autostart', e.target.checked)}
        />
        AivisSpeech のアプリを開かなくても、読み上げエンジンを自動で起動する（画面は表示されません）
      </label>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}

      {policy && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="policy-title">
          <div className="dialog panel">
            <h2 id="policy-title">「{policy.speaker.name}」の利用規約</h2>
            <pre className="policy-text">{policy.text || '（利用規約の本文が提供されていません。配布元の案内を確認してください）'}</pre>
            <div className="actions">
              <button className="btn" onClick={() => setPolicy(null)}>
                閉じる
              </button>
              {!policy.speaker.acknowledged && (
                <button className="btn primary" onClick={() => void acknowledge()}>
                  利用規約を確認し、同意しました
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
