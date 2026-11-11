import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { AppSettings, Speaker, VoiceTune } from '../api/types'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { VoiceMaker, VoiceShop } from './VoiceStudio'

const SPEAKERS: Speaker[] = [
  { name: 'まお', speaker_uuid: 'u1', styles: [{ id: 1, name: 'ノーマル' }], acknowledged: true },
]
const BASE = { tts_speaker: 1, tts_custom_voices: [], tts_voice: null } as unknown as AppSettings

function Maker({ onPreview, seen }: { onPreview: (t: VoiceTune) => void; seen: (s: AppSettings) => void }) {
  const [settings, setSettings] = useState(BASE)
  seen(settings)
  return (
    <VoiceMaker
      settings={settings}
      speakers={SPEAKERS}
      preview={onPreview}
      update={(k, v) => setSettings((s) => ({ ...s, [k]: v }))}
    />
  )
}

describe('VoiceMaker', () => {
  it('makes a voice from a preset, previews it and selects it', async () => {
    const user = userEvent.setup()
    const preview = vi.fn()
    let latest = BASE
    render(<Maker onPreview={preview} seen={(s) => (latest = s)} />)
    await user.click(screen.getByRole('button', { name: '新しい声を作る' }))
    await user.type(screen.getByLabelText('名前'), 'おじいちゃん風')
    await user.click(screen.getByRole('button', { name: 'おじいちゃん風' }))
    expect(screen.getByLabelText("声の高さ")).toHaveValue("-0.04")
    await user.click(screen.getByRole('button', { name: '試聴' }))
    expect(preview).toHaveBeenCalledWith(expect.objectContaining({ style_id: 1, pitch: -0.04, speed: 0.85 }))
    await user.click(screen.getByRole('button', { name: 'この声を使う' }))
    expect(latest.tts_custom_voices).toHaveLength(1)
    expect(latest.tts_custom_voices[0]).toMatchObject({ name: 'おじいちゃん風', style_id: 1, tempo: 0.6 })
    expect(latest.tts_voice).toBe(latest.tts_custom_voices[0].id)
    expect(screen.getByText('使用中')).toBeInTheDocument()

    // 削除すると、元の声に戻る
    await user.click(screen.getByRole('button', { name: '削除' }))
    expect(latest.tts_custom_voices).toHaveLength(0)
    expect(latest.tts_voice).toBeNull()
  })

  it('needs a name before saving', async () => {
    const user = userEvent.setup()
    render(<Maker onPreview={vi.fn()} seen={() => undefined} />)
    await user.click(screen.getByRole('button', { name: '新しい声を作る' }))
    expect(screen.getByRole('button', { name: 'この声を使う' })).toBeDisabled()
  })
})

const ELDER = {
  aivm_uuid: '696c98a2-c0b7-4fe7-8cf2-c7e9b8a9bd82',
  name: 'おじいちゃんの声',
  description: '落ち着いた声',
  creator: '作者',
  timbre: 'ElderlyMale',
  timbre_label: 'おじいちゃん',
  styles: ['ノーマル'],
  license_type: 'ACML 1.0',
  file_size: 252925401,
  downloads: 100,
  samples: [{ url: 'x', transcript: 'こんにちは' }],
  installed: false,
}

describe('VoiceShop', () => {
  it('does not contact AivisHub until opened, then filters and adds a voice after confirming', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /api/speech/voices/hub': () => jsonResponse({ timbres: [], voices: [ELDER] }),
      'GET /api/speech/voices/hub?timbre=ElderlyMale': () => jsonResponse({ timbres: [], voices: [ELDER] }),
      'GET /api/speech/voices/installed': () => jsonResponse({ models: [], job: null }),
      'POST /api/speech/voices/install': () =>
        jsonResponse({ job: { state: 'installing', aivm_uuid: ELDER.aivm_uuid, name: ELDER.name, error: '' } }, 202),
    })
    render(<VoiceShop onChanged={vi.fn()} />)
    expect(calls).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: '声の一覧を開く' }))
    expect(await screen.findByText('おじいちゃんの声')).toBeInTheDocument()
    expect(screen.getByText(/241MB・ACML 1.0/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'おじいちゃん' }))
    expect(calls.some((c) => c.url === '/api/speech/voices/hub?timbre=ElderlyMale')).toBe(true)

    await user.click(await screen.findByRole('button', { name: '追加' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('約 241MB')
    await user.click(screen.getByRole('button', { name: 'ダウンロードして追加' }))
    expect(await screen.findByRole('status')).toHaveTextContent('「おじいちゃんの声」を追加しています')
    const install = calls.find((c) => c.url === '/api/speech/voices/install')
    expect(JSON.parse(String(install?.init?.body))).toEqual({ aivm_uuid: ELDER.aivm_uuid, confirmed: true })
  })
})
