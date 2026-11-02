import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { AppSettings } from '../api/types'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { VoiceSettings } from './VoiceSettings'

const UUID = 'e756b8e4-b606-4e15-99b1-3f9c6a1b2317'
const BASE = {
  stt_model: 'large-v3-turbo',
  stt_device: 'cpu',
  stt_auto_send: true,
  tts_speaker: 1,
  tts_speed: 1,
  tts_auto_read: true,
} as unknown as AppSettings

const STT = {
  models: [
    { name: 'large-v3-turbo', size_gb: 1.6, description: '高精度', recommended: true, installed: false },
    { name: 'small', size_gb: 0.48, description: '速い', recommended: false, installed: true },
  ],
  models_dir: 'D:\\TanisJr\\models\\whisper',
  loaded: null,
  download: null,
  model: 'large-v3-turbo',
  device: 'cpu',
}

function speakers(acknowledged: boolean) {
  return {
    available: true,
    message: null,
    selected: 1,
    speakers: [{ name: 'まお', speaker_uuid: UUID, styles: [{ id: 1, name: 'ノーマル' }], acknowledged }],
  }
}

function Harness() {
  const [settings, setSettings] = useState(BASE)
  return <VoiceSettings settings={settings} update={(k, v) => setSettings((s) => ({ ...s, [k]: v }))} />
}

describe('VoiceSettings', () => {
  it('requires reading the voice license before use', async () => {
    const user = userEvent.setup()
    let acked = false
    const calls = mockFetch({
      'GET /api/speech/stt/status': () => jsonResponse(STT),
      'GET /api/speech/tts/speakers': () => jsonResponse(speakers(acked)),
      [`GET /api/speech/tts/speakers/${UUID}/policy`]: () => jsonResponse({ policy: '商用利用時はクレジット表記が必要です。' }),
      'POST /api/speech/tts/acknowledge': () => {
        acked = true
        return jsonResponse({ acknowledged: true })
      },
    })
    render(<Harness />)
    await user.click(await screen.findByRole('button', { name: '利用規約を確認' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('商用利用時はクレジット表記が必要です。')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '利用規約を確認し、同意しました' }))
    expect(await screen.findByText(/利用規約 確認済み/)).toBeInTheDocument()
    const ack = calls.find((c) => c.url === '/api/speech/tts/acknowledge')!
    expect(JSON.parse(String(ack.init!.body))).toEqual({ speaker_uuid: UUID })
  })

  it('confirms size and location before downloading a Whisper model', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /api/speech/stt/status': () => jsonResponse(STT),
      'GET /api/speech/tts/speakers': () => jsonResponse(speakers(true)),
      'POST /api/speech/stt/models/download': () => jsonResponse({ started: true }),
    })
    render(<Harness />)
    await user.click(await screen.findByRole('button', { name: 'ダウンロード（約1.6GB）' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('D:\\TanisJr\\models\\whisper')).toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('/download'))).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'ダウンロードする' }))
    const req = calls.find((c) => c.url.includes('/download'))!
    expect(JSON.parse(String(req.init!.body))).toEqual({ model: 'large-v3-turbo', confirmed: true })
  })

  it('explains when AivisSpeech is not running', async () => {
    mockFetch({
      'GET /api/speech/stt/status': () => jsonResponse(STT),
      'GET /api/speech/tts/speakers': () =>
        jsonResponse({ available: false, message: 'AivisSpeech に接続できません。', speakers: [], selected: null }),
    })
    render(<Harness />)
    expect(await screen.findByText(/AivisSpeech に接続できません/)).toBeInTheDocument()
  })
})
