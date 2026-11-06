import { act, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { jsonResponse, mockFetch, sseResponse } from '../test/fetchMock'
import { renderWithConversation } from '../test/render'
import { ChatPage, CONVERSATION_MS } from './ChatPage'

// 呼びかけの待ち受けは、名前を呼ばれたことにする関数だけを取り出す
const wake = vi.hoisted(() => ({ onWake: null as null | ((rest: string) => void), active: false }))
vi.mock('../state/useWakeWord', () => ({
  useWakeWord: (options: { active: boolean; onWake: (rest: string) => void }) => {
    wake.onWake = options.onWake
    wake.active = options.active
    return { listening: options.active }
  },
}))

// マイクは使わない（録音を始めたことだけ分かればよい）
vi.mock('../audio/Recorder', () => {
  class Recorder {
    onAutoStop?: () => void
    async start() {}
    async stop() {
      return new Blob()
    }
    cancel() {}
    level() {
      return 0
    }
  }
  class RecorderError extends Error {}
  return { Recorder, RecorderError }
})

// 話しかけを待つ時間を確かめるため、話し終わり判定に渡した設定を記録する
const detectors = vi.hoisted(() => [] as { noSpeechTimeoutMs?: number }[])
vi.mock('../lib/endpointing', () => ({
  EndpointDetector: class {
    heardSpeech = false
    threshold = 0.1
    constructor(options: { noSpeechTimeoutMs?: number }) {
      detectors.push(options)
    }
    update() {
      return null
    }
  },
}))

const MODEL_OK = {
  ollama_available: true,
  message: null,
  installed: [{ name: 'qwen3:8b', size_gb: 5.2 }],
  configured_model: 'qwen3:8b',
  configured_model_installed: true,
  catalog: [],
  storage_path: '',
  free_space_gb: 100,
}

function setup() {
  return mockFetch({
    'GET /api/settings': () =>
      jsonResponse({ wake_enabled: true, wake_reading: 'うるし', stt_auto_send: false, voice_handsfree: false, voice_auto_stop: true }),
    'GET /api/models/status': () => jsonResponse(MODEL_OK),
    'GET /api/speech/stt/status': () =>
      jsonResponse({ models: [{ name: 'large-v3-turbo', installed: true }], model: 'large-v3-turbo', device: 'cuda' }),
    'POST /api/speech/stt/warmup': () => jsonResponse({ started: true }),
    'POST /api/chat': () => sseResponse([{ type: 'token', content: '明日は空いてるよ。' }, { type: 'done', model: 'qwen3:8b' }]),
  })
}

describe('ChatPage: 名前を呼んで始めた会話', () => {
  it('keeps listening for 5 minutes without the name after waking', async () => {
    detectors.length = 0
    const calls = setup()
    renderWithConversation(<ChatPage aiName="漆" />)
    await vi.waitFor(() => expect(wake.active).toBe(true))

    // 「ねえ漆、明日の予定は？」で起きる → そのまま送る
    act(() => wake.onWake!('明日の予定は？'))
    expect(await screen.findByText('明日は空いてるよ。')).toBeInTheDocument()
    const body = JSON.parse(String(calls.find((c) => c.url === '/api/chat')!.init!.body))
    expect(body.messages.at(-1)).toEqual({ role: 'user', content: '明日の予定は？' })

    // 返事のあと、名前を呼ばなくても聞き取りを始め、話しかけを5分待つ
    await vi.waitFor(() => expect(screen.getByText(/聞いています/)).toBeInTheDocument(), { timeout: 3000 })
    const waitMs = detectors.at(-1)!.noSpeechTimeoutMs!
    expect(waitMs).toBeGreaterThan(CONVERSATION_MS - 5000)
    expect(waitMs).toBeLessThanOrEqual(CONVERSATION_MS)
    expect(screen.getByText(/名前を呼ばなくても続けて話せます/)).toBeInTheDocument()
    // 会話の途中は、呼びかけの待ち受けを止めている
    expect(wake.active).toBe(false)
  })

  it('starts listening right away when only the name was called', async () => {
    detectors.length = 0
    setup()
    renderWithConversation(<ChatPage aiName="漆" />)
    await vi.waitFor(() => expect(wake.active).toBe(true))
    act(() => wake.onWake!(''))
    await vi.waitFor(() => expect(screen.getByText(/聞いています/)).toBeInTheDocument())
    expect(detectors.at(-1)!.noSpeechTimeoutMs).toBeGreaterThan(CONVERSATION_MS - 5000)
  })
})
