/** 話し終わり判定の結果 */
export type EndpointEvent = 'speech' | 'end' | 'no-speech' | null

export interface EndpointOptions {
  /** この長さ黙ったら話し終わりとみなす */
  silenceMs: number
  /** 話し始めとみなすのに必要な、声が続く長さ */
  minSpeechMs?: number
  /** 話し始めないまま、この時間が過ぎたらあきらめる */
  noSpeechTimeoutMs?: number
  /** 最初のこの時間で周囲の雑音の大きさを測る */
  calibrationMs?: number
  /** 声とみなす音量の下限 */
  minThreshold?: number
}

/**
 * マイクの音量（0〜1）から、話し始めと話し終わりを判定する。
 * 周囲の雑音の大きさを最初に測り、それより十分大きい音を「声」とみなす。
 */
export class EndpointDetector {
  private readonly silenceMs: number
  private readonly minSpeechMs: number
  private readonly noSpeechTimeoutMs: number
  private readonly calibrationMs: number
  private readonly minThreshold: number
  private startedAt: number | null = null
  private noise = 0
  private noiseSamples = 0
  private voiceSince: number | null = null
  private quietSince: number | null = null
  private speaking = false
  private done = false

  constructor(options: EndpointOptions) {
    this.silenceMs = options.silenceMs
    this.minSpeechMs = options.minSpeechMs ?? 200
    this.noSpeechTimeoutMs = options.noSpeechTimeoutMs ?? 10_000
    this.calibrationMs = options.calibrationMs ?? 300
    this.minThreshold = options.minThreshold ?? 0.06
  }

  /** 声とみなす音量のしきい値 */
  get threshold(): number {
    return Math.max(this.minThreshold, this.noise * 2.5)
  }

  get heardSpeech(): boolean {
    return this.speaking
  }

  update(level: number, now: number): EndpointEvent {
    if (this.done) return null
    if (this.startedAt === null) this.startedAt = now
    const elapsed = now - this.startedAt

    if (elapsed < this.calibrationMs) {
      this.noise = (this.noise * this.noiseSamples + level) / (this.noiseSamples + 1)
      this.noiseSamples += 1
      return null
    }

    const loud = level >= this.threshold
    if (!this.speaking) {
      if (loud) {
        this.voiceSince ??= now
        if (now - this.voiceSince >= this.minSpeechMs) {
          this.speaking = true
          this.quietSince = null
          return 'speech'
        }
      } else {
        this.voiceSince = null
      }
      if (elapsed >= this.noSpeechTimeoutMs) {
        this.done = true
        return 'no-speech'
      }
      return null
    }

    if (loud) {
      this.quietSince = null
      return null
    }
    this.quietSince ??= now
    if (now - this.quietSince >= this.silenceMs) {
      this.done = true
      return 'end'
    }
    return null
  }
}
