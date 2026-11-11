import { api, errorMessage } from '../api/client'
import type { VoiceTune } from '../api/types'

/**
 * 読み上げキュー。文ごとに合成を先行して開始し、順番に再生する。
 * 再生中の音量（level）はアバターの口パクに使う。
 */
export class SpeechPlayer {
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private samples = new Float32Array(1024)
  private chain: Promise<void> = Promise.resolve()
  private synthChain: Promise<void> = Promise.resolve()
  private generation = 0
  private pending = 0
  private current: AudioBufferSourceNode | null = null
  private controller = new AbortController()

  onSpeakingChange?: (speaking: boolean) => void
  onError?: (message: string) => void
  /** 1つの文の再生を始める直前に呼ばれる（文ごとに表情を変えるため） */
  onChunkStart?: (text: string) => void

  private context(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext()
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 1024
      this.analyser.connect(this.ctx.destination)
    }
    return this.ctx
  }

  /** ブラウザーの自動再生制限を解除する（ボタン操作などの直後に呼ぶ） */
  unlock(): void {
    // 音声に対応していない環境（テスト環境など）では何もしない
    if (typeof AudioContext === 'undefined') return
    void this.context().resume()
  }

  /** voice: 元の声のスタイル id か、試聴用の調整（未指定なら設定の声） */
  enqueue(text: string, voice?: number | VoiceTune): void {
    const generation = this.generation
    const ctx = this.context()
    const signal = this.controller.signal
    // 合成は再生より先に進めておくが、同時には1件ずつ行う。
    // 一度に全部頼むとエンジンが分散して処理し、最初の1文が出るまでが遅くなるため。
    const audio = this.synthChain
      .then(() => (generation === this.generation ? api.synthesize(text, voice, signal) : Promise.reject(new Error('stopped'))))
      .then((buf) => ctx.decodeAudioData(buf))
    this.synthChain = audio.then(
      () => undefined,
      () => undefined,
    )
    audio.catch(() => undefined)
    this.setPending(this.pending + 1)
    this.chain = this.chain
      .then(async () => {
        if (generation !== this.generation) return
        let buffer: AudioBuffer
        try {
          buffer = await audio
        } catch (err) {
          if (generation === this.generation && !signal.aborted) this.onError?.(errorMessage(err))
          return
        }
        if (generation !== this.generation) return
        this.onChunkStart?.(text)
        await this.play(buffer)
      })
      .finally(() => {
        if (generation === this.generation) this.setPending(this.pending - 1)
      })
  }

  private play(buffer: AudioBuffer): Promise<void> {
    return new Promise((resolve) => {
      const ctx = this.context()
      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(this.analyser!)
      source.onended = () => {
        if (this.current === source) this.current = null
        resolve()
      }
      this.current = source
      void ctx.resume().then(() => source.start())
    })
  }

  stop(): void {
    this.generation += 1
    this.controller.abort()
    this.controller = new AbortController()
    try {
      this.current?.stop()
    } catch {
      // 再生開始前に停止した場合
    }
    this.current = null
    this.chain = Promise.resolve()
    this.synthChain = Promise.resolve()
    this.setPending(0)
  }

  /** 現在の再生音量（0〜1 程度） */
  level(): number {
    if (!this.analyser || !this.current) return 0
    this.analyser.getFloatTimeDomainData(this.samples)
    let sum = 0
    for (const s of this.samples) sum += s * s
    return Math.min(1, Math.sqrt(sum / this.samples.length) * 4)
  }

  get speaking(): boolean {
    return this.pending > 0
  }

  private setPending(value: number): void {
    const before = this.pending > 0
    this.pending = Math.max(0, value)
    if (before !== this.pending > 0) this.onSpeakingChange?.(this.pending > 0)
  }

  dispose(): void {
    this.stop()
    void this.ctx?.close()
    this.ctx = null
  }
}
