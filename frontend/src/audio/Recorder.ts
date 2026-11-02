const MAX_RECORD_MS = 60_000

export class RecorderError extends Error {}

function micErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'マイクの使用が許可されていません。ブラウザーのアドレスバー付近の設定からマイクを許可してください。'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'マイクが見つかりません。接続を確認してください。'
  if (name === 'NotReadableError') return 'マイクを使用できません。他のアプリが使用していないか確認してください。'
  return 'マイクを開始できませんでした。'
}

/** マイク録音（音声はメモリ上の Blob としてのみ保持する）。 */
export class Recorder {
  private stream: MediaStream | null = null
  private recorder: MediaRecorder | null = null
  private chunks: Blob[] = []
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private samples = new Float32Array(1024)
  private timer: number | undefined
  private finished: Promise<Blob> | null = null

  /** 最大録音時間に達して自動停止したときに呼ばれる */
  onAutoStop?: () => void

  async start(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      throw new RecorderError('このブラウザーは録音に対応していません。')
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      })
    } catch (err) {
      throw new RecorderError(micErrorMessage(err))
    }
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
    this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined)
    this.chunks = []
    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data)
    }
    this.finished = new Promise((resolve) => {
      this.recorder!.onstop = () => resolve(new Blob(this.chunks, { type: this.recorder?.mimeType || 'audio/webm' }))
    })
    this.ctx = new AudioContext()
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 1024
    this.ctx.createMediaStreamSource(this.stream).connect(this.analyser)
    this.recorder.start()
    this.timer = window.setTimeout(() => this.onAutoStop?.(), MAX_RECORD_MS)
  }

  async stop(): Promise<Blob> {
    if (!this.recorder || !this.finished) throw new RecorderError('録音していません。')
    if (this.recorder.state !== 'inactive') this.recorder.stop()
    const blob = await this.finished
    this.release()
    this.chunks = []
    return blob
  }

  cancel(): void {
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop()
    this.release()
    this.chunks = []
  }

  level(): number {
    if (!this.analyser) return 0
    this.analyser.getFloatTimeDomainData(this.samples)
    let sum = 0
    for (const s of this.samples) sum += s * s
    return Math.min(1, Math.sqrt(sum / this.samples.length) * 5)
  }

  private release(): void {
    window.clearTimeout(this.timer)
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    void this.ctx?.close()
    this.ctx = null
    this.analyser = null
  }
}
