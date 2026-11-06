import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Scene } from '../../api/types'
import { SceneBackdrop } from './SceneBackdrop'

const base: Scene = {
  kind: 'room',
  background_id: null,
  place: 'おうち',
  indoor: true,
  period: 'day',
  status: 'おうちでのんびり中',
  sky: null,
  weather: null,
}

describe('SceneBackdrop', () => {
  it.each(['room', 'cafe', 'park', 'street'] as const)('draws the %s scene', (kind) => {
    const { container } = render(<SceneBackdrop scene={{ ...base, kind, indoor: kind === 'room' || kind === 'cafe' }} />)
    expect(container.querySelector('svg.scene-svg')).not.toBeNull()
  })

  it('rains in the window and flashes in a thunderstorm', () => {
    const { container } = render(<SceneBackdrop scene={{ ...base, sky: 'thunder' }} />)
    expect(container.querySelector('rect[fill^="url(#rain-"]')).not.toBeNull()
    expect(container.querySelector('.scene-flash')).not.toBeNull()
  })

  it('shows a custom image with the time-of-day tint', () => {
    const { container } = render(
      <SceneBackdrop scene={{ ...base, kind: 'custom', background_id: 'a'.repeat(32), indoor: false, period: 'night', sky: 'snow' }} />,
    )
    expect(container.querySelector('img')?.getAttribute('src')).toBe(`/api/backgrounds/${'a'.repeat(32)}/file`)
    expect(container.querySelector('.scene-tint')).not.toBeNull()
    expect(container.querySelector('rect[fill^="url(#snow-"]')).not.toBeNull()
  })
})
