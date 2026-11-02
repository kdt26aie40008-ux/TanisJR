import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, SpeakersResponse, SttStatus } from '../api/types'
import { Recorder, RecorderError } from '../audio/Recorder'
import { SpeechPlayer } from '../audio/SpeechPlayer'
import { AvatarStage } from '../components/avatar/AvatarStage'
import type { Activity } from '../components/avatar/AvatarViewer'
import { MessageList } from '../components/MessageList'
import { SaveToggle } from '../components/SaveToggle'
import { detectEmotion, type Emotion } from '../lib/emotion'
import { SentenceChunker } from '../lib/sentences'
import { useConversation } from '../state/ConversationContext'
import { useAvatars } from '../state/useActiveAvatar'

type Phase = 'idle' | 'recording' | 'transcribing' | 'thinking' | 'speaking'

const PHASE_LABELS: Record<Phase, string> = {
  idle: '待機中',
  recording: '録音中…（もう一度押すと終了）',
  transcribing: '音声を認識しています…',
  thinking: '考えています…',
  speaking: '話しています…',
}

export function VoicePage({ aiName }: { aiName: string }) {
  const conversation = useConversation()
  const { messages, streaming, send, stop: stopChat, error: chatError, notice: chatNotice } = conversation
  const { active: avatar } = useAvatars()
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [stt, setStt] = useState<SttStatus | null>(null)
  const [speakers, setSpeakers] = useState<SpeakersResponse | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [recognized, setRecognized] = useState('')
  const [typed, setTyped] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [emotion, setEmotion] = useState<Emotion>('neutral')
  const [speaking, setSpeaking] = useState(false)
  const [micLevel, setMicLevel] = useState(0)
  const recorderRef = useRef<Recorder | null>(null)
  const playerRef = useRef<SpeechPlayer | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  if (!playerRef.current) playerRef.current = new SpeechPlayer()
  const player = playerRef.current

  useEffect(() => {
    player.onSpeakingChange = setSpeaking
    player.onError = setError
    return () => player.dispose()
  }, [player])

  useEffect(() => {
    api.getSettings().then(setSettings, (err) => setError(errorMessage(err)))
    api.sttStatus().then(setStt, () => undefined)
    // 初回の認識が遅くならないよう、画面を開いた時点でモデルを読み込んでおく
    api.warmupStt().catch(() => undefined)
    api.speakers().then(setSpeakers, () => undefined)
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages])

  // 録音中のマイク音量メーター
  useEffect(() => {
    if (phase !== 'recording') {
      setMicLevel(0)
      return
    }
    const id = window.setInterval(() => setMicLevel(recorderRef.current?.level() ?? 0), 80)
    return () => window.clearInterval(id)
  }, [phase])

  useEffect(() => () => recorderRef.current?.cancel(), [])

  const ttsReady = Boolean(
    speakers?.available &&
      settings?.tts_speaker != null &&
      speakers.speakers.some((s) => s.acknowledged && s.styles.some((st) => st.id === settings.tts_speaker)),
  )
  const sttReady = Boolean(stt?.models.find((m) => m.name === stt.model)?.installed)
  const readAloud = Boolean(settings?.tts_auto_read && ttsReady)

  const speak = useCallback(
    (text: string) => {
      player.unlock()
      player.enqueue(text)
    },
    [player],
  )

  /** 過去の発言をもう一度読み上げる（長文は文ごとに分けて合成する） */
  const replay = (text: string) => {
    player.stop()
    const chunker = new SentenceChunker()
    ;[...chunker.push(text), ...chunker.flush()].forEach(speak)
  }

  const talk = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    player.stop()
    setRecognized('')
    setError('')
    setPhase('thinking')
    const chunker = new SentenceChunker()
    const result = await send(trimmed, {
      onToken: readAloud ? (t) => chunker.push(t).forEach(speak) : undefined,
    })
    if (readAloud) chunker.flush().forEach(speak)
    if (result.reply) setEmotion(detectEmotion(result.reply))
    setPhase('idle')
  }

  const startRecording = async () => {
    setError('')
    setNotice('')
    player.stop()
    player.unlock()
    const recorder = new Recorder()
    recorder.onAutoStop = () => void finishRecording()
    try {
      await recorder.start()
    } catch (err) {
      setError(err instanceof RecorderError ? err.message : 'マイクを開始できませんでした。')
      return
    }
    recorderRef.current = recorder
    setPhase('recording')
  }

  const finishRecording = async () => {
    const recorder = recorderRef.current
    if (!recorder) return
    recorderRef.current = null
    setPhase('transcribing')
    try {
      const audio = await recorder.stop()
      const result = await api.transcribe(audio)
      if (result.notice) setNotice(result.notice)
      if (!result.text) {
        setError('聞き取れませんでした。もう一度話してください。')
        setPhase('idle')
        return
      }
      if (settings?.stt_auto_send ?? true) {
        await talk(result.text)
      } else {
        setRecognized(result.text)
        setPhase('idle')
      }
    } catch (err) {
      setError(err instanceof RecorderError ? err.message : errorMessage(err))
      setPhase('idle')
    }
  }

  const stopAll = () => {
    player.stop()
    stopChat()
    recorderRef.current?.cancel()
    recorderRef.current = null
    setPhase('idle')
  }

  const shownPhase: Phase = phase === 'idle' && speaking ? 'speaking' : phase === 'idle' && streaming ? 'thinking' : phase
  const activity: Activity =
    shownPhase === 'recording' ? 'listening' : shownPhase === 'speaking' ? 'speaking' : shownPhase === 'idle' ? 'idle' : 'thinking'
  const busy = phase === 'transcribing' || phase === 'thinking' || streaming

  return (
    <section className="page voice-page">
      <header className="page-header">
        <h1>音声会話</h1>
        <div className="header-actions">
          <SaveToggle />
        </div>
      </header>

      {stt && !sttReady && (
        <div className="banner warn" role="status">
          音声認識モデル「{stt.model}」がダウンロードされていません。<a href="#/settings">設定画面</a>からダウンロードしてください。
        </div>
      )}
      {speakers && !speakers.available && (
        <div className="banner warn" role="status">
          {speakers.message} 読み上げなしで会話できます。
        </div>
      )}
      {speakers?.available && !ttsReady && (
        <div className="banner warn" role="status">
          読み上げの声が未設定、または利用規約が未確認です。<a href="#/settings">設定画面</a>で声を選んでください。
        </div>
      )}

      <div className="voice-layout">
        <AvatarStage
          avatar={avatar}
          getLevel={() => player.level()}
          emotion={emotion}
          activity={activity}
          emptyMessage={
            <>
              アバターが設定されていません。<a href="#/avatar">3Dアバター画面</a>でVRMファイルを読み込めます。
            </>
          }
        />

        <div className="voice-controls">
          <p className={`phase phase-${shownPhase}`} role="status" aria-live="polite">
            {PHASE_LABELS[shownPhase]}
          </p>
          <button
            className={`mic-button${phase === 'recording' ? ' recording' : ''}`}
            onClick={() => void (phase === 'recording' ? finishRecording() : startRecording())}
            disabled={!sttReady || busy}
            aria-label={phase === 'recording' ? '録音を終了して送信' : '話す（録音開始）'}
            style={{ ['--level' as string]: micLevel }}
          >
            <span aria-hidden>{phase === 'recording' ? '■' : '🎤'}</span>
          </button>
          <div className="actions center">
            <button className="btn small" onClick={stopAll} disabled={phase === 'idle' && !speaking && !streaming}>
              停止
            </button>
          </div>
          <form
            className="typed-input"
            onSubmit={(e) => {
              e.preventDefault()
              const text = typed
              setTyped('')
              void talk(text)
            }}
          >
            <label className="sr-only" htmlFor="voice-typed">
              文字で送る
            </label>
            <input
              id="voice-typed"
              value={typed}
              maxLength={8000}
              placeholder="マイクが使えないときは文字で送れます"
              onChange={(e) => setTyped(e.target.value)}
              disabled={busy || phase === 'recording'}
            />
            <button type="submit" className="btn small" disabled={!typed.trim() || busy || phase === 'recording'}>
              送信
            </button>
          </form>
          {recognized && (
            <form
              className="recognized"
              onSubmit={(e) => {
                e.preventDefault()
                void talk(recognized)
              }}
            >
              <label className="field">
                <span>認識結果（修正してから送信できます）</span>
                <textarea value={recognized} rows={2} onChange={(e) => setRecognized(e.target.value)} />
              </label>
              <div className="actions">
                <button type="button" className="btn" onClick={() => setRecognized('')}>
                  破棄
                </button>
                <button type="submit" className="btn primary">
                  送信
                </button>
              </div>
            </form>
          )}
          {(notice || chatNotice) && (
            <div className="banner warn" role="status">
              {notice || chatNotice}
            </div>
          )}
          {(error || chatError) && (
            <div className="banner error" role="alert">
              {error || chatError}
            </div>
          )}
        </div>
      </div>

      <div className="messages voice-transcript" aria-label="会話の記録">
        {messages.length === 0 && (
          <p className="empty">マイクのボタンを押して {aiName} に話しかけてください。</p>
        )}
        <MessageList aiName={aiName} messages={messages} streaming={streaming} onSpeak={ttsReady ? replay : undefined} />
        <div ref={endRef} />
      </div>
    </section>
  )
}
