import type { ScenePeriod, Sky } from '../api/types'

/** 背景の見た目（空の色・明るさ・明かり）を、時間帯と天気から決める */
export interface SceneLook {
  skyTop: string
  skyBottom: string
  /** 景色全体にかける色（夜は暗く、夕方は橙色に） */
  tint: string
  stars: boolean
  sun: boolean
  moon: boolean
  /** 雲の数 */
  clouds: number
  cloudColor: string
  /** 街灯・部屋の明かりをつけるか */
  lightsOn: boolean
  rain: boolean
  snow: boolean
  thunder: boolean
  fog: boolean
}

type Palette = Record<ScenePeriod, [string, string]>

const SKY: Record<'clear' | 'cloudy' | 'rain' | 'snow', Palette> = {
  clear: {
    dawn: ['#8fa3d9', '#ffcfa8'],
    day: ['#5fb0ea', '#cde9f9'],
    evening: ['#6c63b5', '#ffad7a'],
    night: ['#0b1433', '#27386b'],
  },
  cloudy: {
    dawn: ['#a7a9c4', '#e8cdb9'],
    day: ['#9db0c0', '#dfe6eb'],
    evening: ['#857a9e', '#e3a98c'],
    night: ['#141a2c', '#2c3346'],
  },
  rain: {
    dawn: ['#7e8399', '#b9adaa'],
    day: ['#7d8c9b', '#b8c3cc'],
    evening: ['#5e5a73', '#a08a86'],
    night: ['#0d111c', '#222836'],
  },
  snow: {
    dawn: ['#aab0c6', '#e6e2e4'],
    day: ['#b9c4cf', '#eef2f5'],
    evening: ['#8d88a3', '#d9c3bd'],
    night: ['#1a2030', '#3a4152'],
  },
}

const OUTDOOR_TINT: Record<ScenePeriod, string> = {
  dawn: 'rgba(255, 170, 140, 0.16)',
  day: 'rgba(0, 0, 0, 0)',
  evening: 'rgba(255, 120, 60, 0.2)',
  night: 'rgba(12, 18, 52, 0.55)',
}

const INDOOR_TINT: Record<ScenePeriod, string> = {
  dawn: 'rgba(255, 190, 160, 0.1)',
  day: 'rgba(0, 0, 0, 0)',
  evening: 'rgba(255, 150, 90, 0.12)',
  night: 'rgba(28, 22, 46, 0.34)',
}

export function sceneLook(period: ScenePeriod, sky: Sky | null, indoor: boolean): SceneLook {
  const weather = sky ?? 'clear'
  const group = weather === 'rain' || weather === 'thunder' ? 'rain' : weather === 'snow' ? 'snow' : weather === 'clear' ? 'clear' : 'cloudy'
  const [skyTop, skyBottom] = SKY[group][period]
  const gloomy = group !== 'clear'
  let tint = (indoor ? INDOOR_TINT : OUTDOOR_TINT)[period]
  // くもりや雨の昼間は、景色を少し暗くする
  if (gloomy && period === 'day') tint = indoor ? 'rgba(60, 70, 90, 0.1)' : 'rgba(70, 82, 100, 0.2)'
  return {
    skyTop,
    skyBottom,
    tint,
    stars: period === 'night' && !gloomy,
    sun: (period === 'day' || period === 'dawn') && !gloomy,
    moon: period === 'night' && !gloomy,
    clouds: group === 'clear' ? (period === 'night' ? 0 : 2) : 5,
    cloudColor: period === 'night' ? '#3b4256' : group === 'rain' ? '#8c96a3' : '#f4f6f8',
    lightsOn: period === 'evening' || period === 'night' || (gloomy && period === 'dawn'),
    rain: group === 'rain',
    snow: group === 'snow',
    thunder: weather === 'thunder',
    fog: weather === 'fog',
  }
}

const SKY_ICON: Record<Sky, string> = { clear: '☀', cloudy: '☁', fog: '🌫', rain: '☂', snow: '❄', thunder: '⚡' }

export function skyIcon(sky: Sky, period: ScenePeriod): string {
  return sky === 'clear' && period === 'night' ? '☾' : SKY_ICON[sky]
}
