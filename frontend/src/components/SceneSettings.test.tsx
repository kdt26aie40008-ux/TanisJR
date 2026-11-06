import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AppSettings } from '../api/types'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { SceneSettings } from './SceneSettings'

const SETTINGS = { ai_name: '漆', scene_mode: 'auto', weather_enabled: false, weather_place: '' } as AppSettings
const KOBE = { name: '神戸市', detail: '兵庫県 日本', latitude: 34.69, longitude: 135.18 }

describe('SceneSettings', () => {
  it('searches a place and saves only the chosen one', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /api/backgrounds': () => jsonResponse({ backgrounds: [] }),
      'GET /api/weather/places*': () => jsonResponse({ places: [KOBE] }),
      'POST /api/weather/place': () => jsonResponse({ place: '神戸市（兵庫県 日本）' }),
    })
    const onPlaceSaved = vi.fn()
    render(<SceneSettings settings={SETTINGS} update={vi.fn()} onPlaceSaved={onPlaceSaved} />)

    await user.type(screen.getByLabelText('天気の場所を探す'), '神戸')
    await user.click(screen.getByRole('button', { name: '探す' }))
    await user.click(await screen.findByRole('button', { name: /神戸市/ }))

    expect(onPlaceSaved).toHaveBeenCalledWith(KOBE, '神戸市（兵庫県 日本）')
    const sent = JSON.parse(String(calls.find((c) => c.url === '/api/weather/place')!.init!.body))
    expect(sent).toEqual({ place: KOBE })
    expect(screen.getByRole('status')).toHaveTextContent('天気の場所を「神戸市（兵庫県 日本）」にしました。')
  })

  it('turns the weather forecast on only through the switch', async () => {
    const user = userEvent.setup()
    mockFetch({ 'GET /api/backgrounds': () => jsonResponse({ backgrounds: [] }) })
    const update = vi.fn()
    render(<SceneSettings settings={SETTINGS} update={update} onPlaceSaved={vi.fn()} />)
    await user.click(screen.getByRole('switch'))
    expect(update).toHaveBeenCalledWith('weather_enabled', true)
  })
})
