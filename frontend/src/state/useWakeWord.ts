import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { Recorder } from '../audio/Recorder'
import { EndpointDetector } from '../lib/endpointing'
import { matchWake } from '../lib/wakeMatch'

/** 呼びかけとみなす発話の長さの上限（長い会話は呼びかけではないので文字にしない） */
const MAX_CALL_MS = 6000

interface Options {
  /** 聞いてよい状態か（会話中・録音中・読み上げ中は聞かない） */
  active: boolean
  /** 呼び名（AI の名前と、その読み） */
  names: string[]
  /** 名前を呼ばれたとき。rest は名前に続けて話した内容 */
  onWake: (rest: string) => void
}

/**
 * 「ねえ○○」で起きる。マイクの音から短い発話を切り出し、この PC の中で文字にして名前を探す。
 * 聞いた音は文字にしたらすぐ捨て、保存も送信もしない。
 */
export function useWakeWord({ active, names, onWake }: Options): { listening: boolean } {
  const [listening, setListening] = useState(false)
  const onWakeRef = useRef(onWake)
  onWakeRef.current = onWake
  const namesKey = names.join('\n')

  useEffect(() => {
    if (!active || !names.some((n) => n.trim())) return
    let stopped = false
    let recorder: Recorder | null = null
    let timer: number | undefined

    const listen = async () => {
      if (stopped) return
      const current = new Recorder()
      recorder = current
      // 長い間呼ばれなければ録音を区切り直す（音声をためこまないため）
      current.onAutoStop = () => {
        window.clearInterval(timer)
        current.cancel()
        void listen()
      }
      try {
        await current.start()
      } catch {
        setListening(false)
        return
      }
      if (stopped) {
        current.cancel()
        return
      }
      setListening(true)
      const detector = new EndpointDetector({ silenceMs: 700, minSpeechMs: 250, noSpeechTimeoutMs: Infinity })
      let speechAt = 0
      timer = window.setInterval(() => {
        const now = performance.now()
        const event = detector.update(current.level(), now)
        if (event === 'speech') speechAt = now
        if (event !== 'end') return
        window.clearInterval(timer)
        const long = now - speechAt > MAX_CALL_MS
        void current.stop().then(async (audio) => {
          if (stopped) return
          if (!long) {
            try {
              const { text } = await api.transcribe(audio, { fast: true })
              const match = matchWake(text, names)
              if (match.matched && !stopped) {
                setListening(false)
                onWakeRef.current(match.rest)
                return
              }
            } catch {
              // 聞き取りに失敗しても、待ち受けは続ける
            }
          }
          void listen()
        }, () => undefined)
      }, 50)
    }

    void listen()
    return () => {
      stopped = true
      window.clearInterval(timer)
      recorder?.cancel()
      setListening(false)
    }
    // names は namesKey で比較する
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, namesKey])

  return { listening }
}
