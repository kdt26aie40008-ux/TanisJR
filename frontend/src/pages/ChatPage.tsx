import { Mic, Send, Square, SquarePen } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, errorMessage } from '../api/client'
import type { AppSettings, Scene, SpeakersResponse, SttStatus } from '../api/types'
import { Recorder, RecorderError } from '../audio/Recorder'
import { SpeechPlayer } from '../audio/SpeechPlayer'
import { AvatarStage } from '../components/avatar/AvatarStage'
import type { Activity } from '../components/avatar/AvatarViewer'
import { MessageList } from '../components/MessageList'
import { ModelStatusBanner } from '../components/ModelStatusBanner'
import { SaveToggle } from '../components/SaveToggle'
import { SceneBackdrop } from '../components/scene/SceneBackdrop'
import { skyIcon } from '../lib/sceneLook'
import { chooseBackchannel } from '../lib/backchannel'
import { detectEmotion, type Emotion } from '../lib/emotion'
import { EndpointDetector } from '../lib/endpointing'
import { SpeechFilter } from '../lib/mathText'
import { SentenceChunker } from '../lib/sentences'
import { useConversation } from '../state/ConversationContext'
import { useAvatars } from '../state/useActiveAvatar'
import { useWakeWord } from '../state/useWakeWord'

const MAX_INPUT = 8000
/** 名前を呼んで話し始めたら、この間は名前を呼ばなくても続けて話せる（最後のやりとりから数える） */
export const CONVERSATION_MS = 5 * 60_000
/** 名前だけ呼ばれたときの返事 */
export const WAKE_REPLIES = ['なーに？', 'はーい、なに？', '呼んだ？', 'うん、どうしたの？']

/** 文章全体を文ごとに分けて読み上げる（数式は言葉にし、コードや書式の記号は読まない） */
function speakAll(text: string, speak: (sentence: string) => void): void {
  const chunker = new SentenceChunker()
  const filter = new SpeechFilter()
  for (const sentence of [...chunker.push(text), ...chunker.flush()]) {
    const spoken = filter.next(sentence)
    if (spoken) speak(spoken)
  }
}

type Phase = 'idle' | 'recording' | 'transcribing' | 'thinking' | 'speaking'

const PHASE_LABELS: Record<Phase, string> = {
  idle: 'ここにいるよ',
  recording: '聞いています…',
  transcribing: '聞き取っています…',
  thinking: '考えています…',
  speaking: '話しています…',
}

interface Props {
  aiName: string
  /** 画面が表示されているか（非表示の間は 3D 描画を止める） */
  visible?: boolean
}

/** おしゃべり画面。アバターを中心に、文字でも声でも話せる。 */
export function ChatPage({ aiName, visible = true }: Props) {
  const { messages, streaming, notice, error, send, stop: stopChat, clear, say } = useConversation()
  const { active: avatar } = useAvatars()
  const [input, setInput] = useState('')
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [stt, setStt] = useState<SttStatus | null>(null)
  const [speakers, setSpeakers] = useState<SpeakersResponse | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [recognized, setRecognized] = useState('')
  const [voiceError, setVoiceError] = useState('')
  const [voiceNotice, setVoiceNotice] = useState('')
  const [emotion, setEmotion] = useState<Emotion>('neutral')
  const [speaking, setSpeaking] = useState(false)
  const [micLevel, setMicLevel] = useState(0)
  const [handsfree, setHandsfree] = useState(false)
  // 「続けて話す」で、返事を話し終えたら次の聞き取りを始める合図
  const [relisten, setRelisten] = useState(false)
  // 名前を呼んで始めた会話の途中か（この間は名前を呼ばなくても聞き続ける）
  const [conversing, setConversing] = useState(false)
  const conversingRef = useRef(false)
  conversingRef.current = conversing
  const recorderRef = useRef<Recorder | null>(null)
  const playerRef = useRef<SpeechPlayer | null>(null)
  const detectorRef = useRef<EndpointDetector | null>(null)
  // 割り込みを待つための、読み上げ中のマイク
  const monitorRef = useRef<Recorder | null>(null)
  // いまの返事が声での問いかけに対するものか（割り込みは声の会話の中だけで使う）
  const voiceTurnRef = useRef(false)
  // 返事ごとの番号。止めたときに番号を進め、古い返事の続きを読み上げないようにする
  const turnRef = useRef(0)
  const warmedUp = useRef(false)
  const finishRef = useRef<() => void>(() => undefined)
  const giveUpRef = useRef<() => void>(() => undefined)
  const endRef = useRef<HTMLDivElement>(null)

  if (!playerRef.current) playerRef.current = new SpeechPlayer()
  const player = playerRef.current

  // 描画ループやコールバックから最新の設定を読むための参照
  const settingsRef = useRef(settings)
  settingsRef.current = settings

  useEffect(() => {
    player.onSpeakingChange = setSpeaking
    player.onError = setVoiceError
    // ふるまい「文ごとに表情を変える」: 話し始める文の内容に合わせて表情を変える
    player.onChunkStart = (text) => {
      if (settingsRef.current?.behavior_sentence_emotion ?? true) setEmotion(detectEmotion(text))
    }
    return () => player.dispose()
  }, [player])

  // 設定画面で変えた内容（声の選択・利用規約の確認・音声認識モデルなど）を反映するため、
  // 画面を開くたびに読み直す。失敗しても文字の会話はできるので、ここではエラーを表示しない
  useEffect(() => {
    if (!visible) return
    api.getSettings().then(setSettings, () => undefined)
    api.sttStatus().then(setStt, () => undefined)
    api.speakers().then(setSpeakers, () => undefined)
  }, [visible])

  // 読み上げエンジンが起動中などで使えなかったときは、使えるようになるまで5秒ごとに確認し直す
  // （起動に1分ほどかかるため、開いたときの1回だけでは声が出ないままになる）
  const speakersAvailable = speakers?.available
  useEffect(() => {
    if (!visible || speakersAvailable !== false) return
    const id = window.setInterval(() => api.speakers().then(setSpeakers, () => undefined), 5000)
    return () => window.clearInterval(id)
  }, [visible, speakersAvailable])

  // アバターのいる場所（背景）と天気。時間帯で変わるので、開いている間は5分ごとに読み直す
  const [scene, setScene] = useState<Scene | null>(null)
  useEffect(() => {
    if (!visible) return
    const load = () => api.scene().then((r) => setScene(r.scene), () => undefined)
    load()
    const id = window.setInterval(load, 5 * 60_000)
    return () => window.clearInterval(id)
  }, [visible])

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages])

  // 録音中のマイク音量と、話し終わりの判定
  useEffect(() => {
    if (phase !== 'recording') {
      setMicLevel(0)
      return
    }
    const id = window.setInterval(() => {
      const level = recorderRef.current?.level() ?? 0
      setMicLevel(level)
      const event = detectorRef.current?.update(level, performance.now())
      if (event === 'end') finishRef.current()
      else if (event === 'no-speech') giveUpRef.current()
    }, 50)
    return () => window.clearInterval(id)
  }, [phase])

  useEffect(() => () => recorderRef.current?.cancel(), [])

  // ブラウザーは一度操作されるまで音を出せないため、最初のクリックやキー入力で音声を有効にする
  // （AI から話しかけたときに声を出せるようにするため）
  useEffect(() => {
    const unlock = () => player.unlock()
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    return () => {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }, [player])

  // 読み上げ（AivisSpeech）は日本語専用
  const ttsReady = Boolean(
    (settings?.language ?? 'ja') === 'ja' &&
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
    speakAll(text, speak)
  }

  /**
   * 送信して返事を待つ。読み上げがオンなら文ができるごとに話し始める。
   * afterBackchannel: 直前に相づちを読み上げ中なので、それを止めずに続けて話す
   */
  const talk = async (text: string, options: { afterBackchannel?: boolean } = {}) => {
    const trimmed = text.trim()
    if (!trimmed) return { failed: false }
    if (!options.afterBackchannel) player.stop()
    setRecognized('')
    setVoiceError('')
    setPhase('thinking')
    // 最初のひと言は読点で区切って、少しでも早く話し始める
    const chunker = new SentenceChunker({ eagerFirst: true })
    // 止められたり割り込まれたりした後に届いた続きは読み上げない
    const turn = ++turnRef.current
    // 数式は言葉にして読み、コードや書式の記号は読まない
    const filter = new SpeechFilter()
    const speakTurn = (sentence: string) => {
      const spoken = filter.next(sentence)
      if (spoken && turnRef.current === turn) speak(spoken)
    }
    const result = await send(trimmed, {
      onToken: readAloud ? (t) => chunker.push(t).forEach(speakTurn) : undefined,
    })
    if (readAloud) chunker.flush().forEach(speakTurn)
    // 文ごとに表情を変える場合は、読み上げに合わせて変わるので最後にまとめて変えない
    const perSentence = readAloud && (settings?.behavior_sentence_emotion ?? true)
    if (result.reply && !perSentence) setEmotion(detectEmotion(result.reply))
    // 途中で割り込まれて聞き取りを始めていたら、そのままにする
    setPhase((current) => (current === 'recording' ? current : 'idle'))
    return result
  }

  /** ふるまい「相づち」: 声で話し終えたら、考える前に、話した内容に合った相づちを短く返す */
  const lastBackchannel = useRef('')
  const backchannel = (heard: string): boolean => {
    if (!readAloud || !(settings?.behavior_backchannel ?? true)) return false
    const word = chooseBackchannel(heard, lastBackchannel.current)
    if (!word) return false
    lastBackchannel.current = word
    player.stop()
    speak(word)
    return true
  }

  const submit = async () => {
    const text = input.trim()
    if (!text || streaming) return
    voiceTurnRef.current = false
    setInput('')
    // ブラウザーは操作のきっかけがないと音を出せないため、送信の操作で音声を有効にしておく
    if (readAloud) player.unlock()
    const result = await talk(text)
    // 失敗したら入力を戻して再送できるようにする
    if (result.failed) setInput((current) => current || text)
  }

  /** 初回の聞き取りが遅くならないよう、マイクに触れた時点で音声認識を準備する */
  const warmUp = () => {
    if (warmedUp.current || !sttReady) return
    warmedUp.current = true
    api.warmupStt().catch(() => undefined)
  }

  const autoStop = settings?.voice_auto_stop ?? true

  /**
   * 聞き取りを始める。
   * 名前を呼んで始めた会話の途中なら、話しかけを最大5分待つ（waitUntil まで）。
   */
  const startRecording = async (waitUntil?: number) => {
    setVoiceError('')
    if (waitUntil === undefined) setVoiceNotice('')
    warmUp()
    player.stop()
    player.unlock()
    const recorder = new Recorder()
    const detector = autoStop
      ? new EndpointDetector({
          silenceMs: settings?.voice_silence_ms ?? 1200,
          noSpeechTimeoutMs: waitUntil === undefined ? undefined : Math.max(1000, waitUntil - Date.now()),
        })
      : null
    recorder.onAutoStop = () => {
      // 会話の途中で黙って待っている間は、録音を区切り直して待ち続ける（音声をためこまない）
      if (waitUntil !== undefined && detector && !detector.heardSpeech && recorderRef.current === recorder) {
        recorder.cancel()
        recorderRef.current = null
        void startRecording(waitUntil)
        return
      }
      void finishRecording()
    }
    try {
      await recorder.start()
    } catch (err) {
      setVoiceError(err instanceof RecorderError ? err.message : 'マイクを開始できませんでした。')
      setHandsfree(false)
      setConversing(false)
      return
    }
    recorderRef.current = recorder
    detectorRef.current = detector
    setPhase('recording')
  }

  /** 名前を呼ばれた。ここから5分間は、名前を呼ばなくても続けて話せる */
  const startConversation = (rest: string) => {
    setConversing(true)
    setHandsfree(true)
    setVoiceNotice('')
    if (rest) {
      voiceTurnRef.current = true
      void talk(rest).then((reply) => {
        setRelisten(!reply.failed)
        if (reply.failed) endConversation()
      })
    } else {
      // 名前だけ呼ばれたら「なーに？」と返事をしてから聞く
      const reply = WAKE_REPLIES[Math.floor(Math.random() * WAKE_REPLIES.length)]
      say(reply)
      setEmotion('happy')
      if (readAloud) {
        speak(reply)
        // 返事を話し終えたら聞き取りを始める（自分の声を拾わないように）
        setRelisten(true)
      } else {
        void startRecording(Date.now() + CONVERSATION_MS)
      }
    }
  }

  /** マイクのボタンから話し始める。「続けて話す」がオンなら、止めるまで会話を続ける */
  const startByUser = () => {
    setHandsfree(Boolean(settings?.voice_handsfree && settings.stt_auto_send))
    setConversing(false)
    void startRecording()
  }

  const finishRecording = async () => {
    const recorder = recorderRef.current
    if (!recorder) return
    recorderRef.current = null
    detectorRef.current = null
    setPhase('transcribing')
    try {
      const audio = await recorder.stop()
      // 名前を呼んで始めた会話では、聞き取った言葉をそのまま送る
      const autoSend = (settings?.stt_auto_send ?? true) || conversingRef.current
      const result = await api.transcribe(audio)
      if (result.notice) setVoiceNotice(result.notice)
      if (!result.text) {
        if (conversingRef.current) {
          // 会話の途中で物音などを拾っただけなら、何も言わずに聞き直す
          setPhase('idle')
          setRelisten(true)
          return
        }
        setVoiceError('聞き取れませんでした。もう一度話してください。')
        setHandsfree(false)
        setPhase('idle')
        return
      }
      // 聞き取りの間を埋めるため、送る前に相づちを入れる
      const backchanneled = autoSend && backchannel(result.text)
      if (autoSend) {
        voiceTurnRef.current = true
        const reply = await talk(result.text, { afterBackchannel: backchanneled })
        setRelisten(!reply.failed)
        if (reply.failed) endConversation()
      } else {
        setRecognized(result.text)
        setPhase('idle')
      }
    } catch (err) {
      setVoiceError(err instanceof RecorderError ? err.message : errorMessage(err))
      setHandsfree(false)
      setConversing(false)
      setPhase('idle')
    }
  }

  /** 返事を受け取れなかったら、名前を呼んで始めた会話はいったん終える（また呼べば再開できる） */
  const endConversation = () => {
    if (!conversingRef.current) return
    setConversing(false)
    setHandsfree(false)
  }

  /** 話しかけがないまま時間が過ぎたら、聞くのをやめる（録音は捨てる） */
  const giveUp = () => {
    recorderRef.current?.cancel()
    recorderRef.current = null
    detectorRef.current = null
    setHandsfree(false)
    setPhase('idle')
    if (conversingRef.current) {
      setConversing(false)
      setVoiceNotice(`しばらく話しかけがなかったので、会話を終えました。また「ねえ、${aiName}」で呼んでね。`)
      return
    }
    setVoiceNotice('話しかけがなかったので、聞くのをやめました。')
  }

  finishRef.current = () => void finishRecording()
  giveUpRef.current = giveUp

  // 「続けて話す」: 返事を話し終えたら、少し間をおいて次の聞き取りを始める
  useEffect(() => {
    if (!handsfree || !relisten || phase !== 'idle' || speaking || streaming) return
    const id = window.setTimeout(() => {
      setRelisten(false)
      // 名前を呼んで始めた会話なら、返事を話し終えてから5分間、話しかけを待つ
      void startRecording(conversingRef.current ? Date.now() + CONVERSATION_MS : undefined)
    }, 600)
    return () => window.clearTimeout(id)
    // startRecording は毎回作り直されるため依存に含めない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handsfree, relisten, phase, speaking, streaming])

  // ふるまい「割り込み」: 声で会話している間は、話している最中もマイクを聞いておき、
  // 話しかけられたら読み上げを止めて、その録音をそのまま聞き取りに使う
  const bargeIn = (monitor: Recorder, threshold: number) => {
    monitorRef.current = null
    turnRef.current += 1
    player.stop()
    if (streaming) stopChat()
    setRelisten(false)
    recorderRef.current = monitor
    // すでに話し始めているので、雑音の測定と話し始めの判定は省く
    detectorRef.current = autoStop
      ? new EndpointDetector({
          silenceMs: settings?.voice_silence_ms ?? 1200,
          calibrationMs: 0,
          minSpeechMs: 0,
          minThreshold: threshold,
        })
      : null
    setPhase('recording')
  }
  const bargeInRef = useRef(bargeIn)
  bargeInRef.current = bargeIn

  // 聞き取り中・録音中は、割り込み用のマイクは使わない
  const monitorWanted = Boolean(
    speaking && settings?.behavior_barge_in && sttReady && phase !== 'transcribing' && phase !== 'recording',
  )
  useEffect(() => {
    if (!monitorWanted || !voiceTurnRef.current || recorderRef.current) return
    let cancelled = false
    const monitor = new Recorder()
    // スピーカーの音を拾いにくくするため、話し始めの判定は普段より厳しくする
    const detector = new EndpointDetector({ silenceMs: 1000, minSpeechMs: 350, minThreshold: 0.15, noSpeechTimeoutMs: Infinity })
    let id: number | undefined
    monitor.onAutoStop = () => monitor.cancel()
    monitor.start().then(
      () => {
        if (cancelled) {
          monitor.cancel()
          return
        }
        monitorRef.current = monitor
        id = window.setInterval(() => {
          if (detector.update(monitor.level(), performance.now()) === 'speech') {
            window.clearInterval(id)
            bargeInRef.current(monitor, detector.threshold)
          }
        }, 50)
      },
      () => undefined,
    )
    return () => {
      cancelled = true
      window.clearInterval(id)
      // 割り込みに使われなかった録音は捨てる
      if (monitorRef.current === monitor) {
        monitorRef.current = null
        monitor.cancel()
      }
    }
  }, [monitorWanted])

  const stopAll = () => {
    setHandsfree(false)
    setConversing(false)
    setRelisten(false)
    voiceTurnRef.current = false
    turnRef.current += 1
    player.stop()
    stopChat()
    recorderRef.current?.cancel()
    recorderRef.current = null
    detectorRef.current = null
    setPhase('idle')
  }

  // ----- 自分から話しかける（アプリを開いている間、1分ごとに確認する） -----
  const lastActivityRef = useRef(Date.now())
  useEffect(() => {
    lastActivityRef.current = Date.now()
  }, [messages])
  const proactiveRef = useRef<() => void>(() => undefined)
  proactiveRef.current = () => {
    if (phase !== 'idle' || streaming || speaking || recorderRef.current || handsfree || recognized) return
    const idleMinutes = Math.floor((Date.now() - lastActivityRef.current) / 60000)
    api.proactiveNext(idleMinutes).then(
      (result) => {
        if (!result.kind || !result.text) return
        // 確認している間に会話が始まっていたら、話しかけない
        if (stateBusyRef.current) return
        say(result.text)
        lastActivityRef.current = Date.now()
        if (readAloud) {
          speakAll(result.text, (s) => player.enqueue(s))
        } else {
          setEmotion(detectEmotion(result.text))
        }
      },
      () => undefined,
    )
  }
  const stateBusyRef = useRef(false)
  stateBusyRef.current = phase !== 'idle' || streaming || Boolean(recorderRef.current)
  const proactiveOn = Boolean(settings?.proactive_enabled)
  useEffect(() => {
    if (!proactiveOn) return
    const first = window.setTimeout(() => proactiveRef.current(), 4000)
    const id = window.setInterval(() => proactiveRef.current(), 60_000)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(id)
    }
  }, [proactiveOn])

  // ----- 「ねえ○○」で起きる -----
  const wakeActive = Boolean(
    settings?.wake_enabled &&
      sttReady &&
      phase === 'idle' &&
      !speaking &&
      !streaming &&
      !handsfree &&
      !recognized &&
      !monitorWanted,
  )
  // 呼びかけを待つときも音声認識を先に準備する（GPU の初回は20秒ほどかかるため）
  useEffect(() => {
    if (wakeActive) warmUp()
    // warmUp は毎回作り直されるため依存に含めない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wakeActive])
  const { listening: waitingForCall } = useWakeWord({
    active: wakeActive,
    names: [aiName, settings?.wake_reading ?? ''],
    onWake: (rest) => {
      if (!visible) window.location.hash = '#/chat'
      startConversation(rest)
    },
  })

  const shownPhase: Phase = phase === 'idle' && speaking ? 'speaking' : phase === 'idle' && streaming ? 'thinking' : phase
  const activity: Activity =
    shownPhase === 'recording' ? 'listening' : shownPhase === 'speaking' ? 'speaking' : shownPhase === 'idle' ? 'idle' : 'thinking'
  const busy = phase === 'transcribing' || phase === 'thinking' || streaming
  const canStop = phase !== 'idle' || speaking || streaming
  const micTitle = !stt
    ? '音声認識の状態を確認しています'
    : !sttReady
      ? '声で話すには、設定の「声」で音声認識をダウンロードしてください'
      : phase === 'recording'
        ? autoStop
          ? '黙ると自動で送ります（押すとすぐ送ります）'
          : '話し終わったら押してください'
        : '声で話す'

  const weather = scene?.weather
  return (
    <section className="page chat-page immersive">
      {/* アバターのいる場所（時間帯と天気で変わる） */}
      <SceneBackdrop scene={scene} />

      <div className="stage-avatar" aria-label={`${aiName} のようす`}>
        {visible ? (
          <AvatarStage
            avatar={avatar}
            getLevel={() => player.level()}
            emotion={emotion}
            activity={activity}
            nod={settings?.behavior_nod ?? true}
            gaze={settings?.behavior_gaze ?? true}
            getListenLevel={() => recorderRef.current?.level() ?? 0}
            framing="wide"
            emptyMessage={
              <>
                まだすがたがありません。<a href="#/avatar">「すがた」</a>で選ぶと、ここに {aiName} が現れます。
              </>
            }
          />
        ) : (
          <div className="avatar-stage empty" />
        )}
      </div>

      <header className="stage-hud">
        <div className="hud-left">
          <h1 className="hud-name">{aiName}</h1>
          <span className={`status-pill phase-${shownPhase}`} role="status" aria-live="polite">
            <span className="status-dot" aria-hidden />
            {shownPhase === 'recording' && autoStop
              ? '聞いています…（黙ると送ります）'
              : shownPhase === 'idle' && waitingForCall
                ? `「ねえ、${aiName}」で呼んでね`
                : PHASE_LABELS[shownPhase]}
          </span>
          {scene && (
            <span className="scene-chip" title={scene.place}>
              {scene.sky && <span aria-hidden>{skyIcon(scene.sky, scene.period)}</span>}
              {scene.status}
              {weather && (
                <span className="scene-weather-text">
                  {weather.place.split('（')[0]} {weather.label}
                  {weather.temperature != null && ` ${Math.round(weather.temperature)}℃`}
                  {weather.today.rain_chance != null && ` ・ 降水${weather.today.rain_chance}%`}
                </span>
              )}
            </span>
          )}
        </div>
        <div className="hud-right">
          <div className="save-toggle">
            <SaveToggle />
          </div>
          <button
            className="btn small ghost glass"
            onClick={clear}
            disabled={streaming || messages.length === 0}
            title="新しい会話をはじめる"
          >
            <SquarePen size={16} aria-hidden />
            新しい会話
          </button>
        </div>
      </header>

      {waitingForCall &&
        createPortal(
          <div className="wake-indicator" role="status">
            <Mic size={14} aria-hidden />
            呼ばれるのを待っています（マイク使用中）
          </div>,
          document.body,
        )}

      <div className="chat-overlay">
        <ModelStatusBanner />
        {notice && (
          <div className="banner warn" role="status">
            {notice}
          </div>
        )}
        <div className="messages" aria-live="polite">
          {messages.length === 0 && (
            <p className="empty">
              {aiName} に話しかけてみよう。意見が違うときは、{aiName} は遠慮なく言い返します。
              <br />
              <span className="hint">「この会話を保存」をオンにすると、{aiName} はあなたのことを少しずつ覚えていきます。</span>
            </p>
          )}
          <MessageList aiName={aiName} messages={messages} streaming={streaming} onSpeak={ttsReady ? replay : undefined} />
          <div ref={endRef} />
        </div>

        {error && (
          <div className="banner error" role="alert">
            {error}
          </div>
        )}
        {voiceNotice && (
          <div className="banner warn" role="status">
            {voiceNotice}
          </div>
        )}
        {voiceError && (
          <div className="banner error" role="alert">
            {voiceError}
          </div>
        )}
        {handsfree && (
          <p className="hint overlay-hint">
            {conversing
              ? '名前を呼ばなくても続けて話せます。5分ほど話しかけがないと終わります（すぐ終えるときは「止める」）。'
              : '続けて話せます。おしまいにするときは「止める」を押してください。'}
          </p>
        )}
        {stt && !sttReady && (
          <p className="hint overlay-hint">
            声で話すには、<a href="#/settings">設定</a>の「声」で音声認識を準備してください。
          </p>
        )}
        {speakers && !speakers.available && <p className="hint overlay-hint">{speakers.message} 声なしでも話せます。</p>}
        {speakers?.available && !ttsReady && (
          <p className="hint overlay-hint">
            {aiName} の声が決まっていません。<a href="#/settings">設定</a>の「声」で選べます。
          </p>
        )}
        {recognized && (
          <form
            className="recognized"
            onSubmit={(e) => {
              e.preventDefault()
              void talk(recognized)
            }}
          >
            <label className="field">
              <span>聞き取った内容（直してから送れます）</span>
              <textarea value={recognized} rows={2} onChange={(e) => setRecognized(e.target.value)} />
            </label>
            <div className="actions">
              <button type="button" className="btn small" onClick={() => setRecognized('')}>
                やめる
              </button>
              <button type="submit" className="btn small primary">
                送る
              </button>
            </div>
          </form>
        )}

        <form
          className="composer chat-composer"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <button
            type="button"
            className={`mic-button${phase === 'recording' ? ' recording' : ''}`}
            onClick={() => (phase === 'recording' ? void finishRecording() : startByUser())}
            onPointerEnter={warmUp}
            disabled={!sttReady || busy}
            title={micTitle}
            aria-label={phase === 'recording' ? '話し終わって送る' : '声で話す'}
            style={{ ['--level' as string]: micLevel }}
          >
            {phase === 'recording' ? <Square size={20} aria-hidden /> : <Mic size={22} aria-hidden />}
          </button>
          <label className="sr-only" htmlFor="chat-input">
            メッセージ
          </label>
          <textarea
            id="chat-input"
            value={input}
            rows={1}
            maxLength={MAX_INPUT}
            placeholder={`${aiName} に話しかける`}
            title="Enterで送信 / Shift+Enterで改行"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // 日本語入力の変換確定の Enter では送信しない
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                void submit()
              }
            }}
          />
          {(canStop || handsfree) && !streaming && (
            <button type="button" className="btn small" onClick={stopAll}>
              止める
            </button>
          )}
          {streaming ? (
            <button type="button" className="btn" onClick={stopAll}>
              停止
            </button>
          ) : (
            <button type="submit" className="btn primary icon-btn" disabled={!input.trim()} aria-label="送信">
              <Send size={18} aria-hidden />
            </button>
          )}
        </form>
      </div>
    </section>
  )
}
