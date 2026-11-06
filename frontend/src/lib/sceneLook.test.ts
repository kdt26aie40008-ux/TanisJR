import { describe, expect, it } from 'vitest'
import { sceneLook, skyIcon } from './sceneLook'

describe('sceneLook', () => {
  it('darkens the night and turns on the lights', () => {
    const night = sceneLook('night', 'clear', false)
    expect(night.stars && night.moon && night.lightsOn).toBe(true)
    expect(night.tint).toMatch(/0\.55\)$/)
    const day = sceneLook('day', 'clear', false)
    expect(day.sun && !day.lightsOn && !day.stars).toBe(true)
  })

  it('shows rain, snow and thunder', () => {
    expect(sceneLook('day', 'rain', false).rain).toBe(true)
    const storm = sceneLook('day', 'thunder', false)
    expect(storm.rain && storm.thunder && !storm.sun).toBe(true)
    expect(sceneLook('day', 'snow', true).snow).toBe(true)
    expect(sceneLook('day', 'fog', false).fog).toBe(true)
  })

  it('uses a warm evening sky and keeps indoor scenes lighter', () => {
    expect(sceneLook('evening', 'clear', false).skyBottom).toBe('#ffad7a')
    expect(sceneLook('night', null, true).tint).not.toBe(sceneLook('night', null, false).tint)
  })

  it('picks a weather icon', () => {
    expect(skyIcon('rain', 'day')).toBe('☂')
    expect(skyIcon('clear', 'night')).toBe('☾')
  })
})
