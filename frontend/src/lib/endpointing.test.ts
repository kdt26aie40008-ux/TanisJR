import { describe, expect, it } from 'vitest'
import { EndpointDetector, type EndpointEvent } from './endpointing'

/** [音量, 続く時間ms] の並びを 50ms 刻みで流し、起きたイベントと時刻を返す */
function run(detector: EndpointDetector, pattern: [number, number][]) {
  const events: [EndpointEvent, number][] = []
  let t = 0
  for (const [level, ms] of pattern) {
    for (let i = 0; i < ms; i += 50, t += 50) {
      const e = detector.update(level, t)
      if (e) events.push([e, t])
    }
  }
  return events
}

describe('EndpointDetector', () => {
  it('ends after the configured silence once speech was heard', () => {
    const d = new EndpointDetector({ silenceMs: 1000 })
    const events = run(d, [
      [0.02, 300], // 周囲の雑音を測る
      [0.3, 1000], // 話す
      [0.02, 2000], // 黙る
    ])
    expect(events.map((e) => e[0])).toEqual(['speech', 'end'])
    // 黙り始め（1300ms）から 1000ms 後に終わる
    expect(events[1][1]).toBe(2300)
  })

  it('does not end on a short pause in the middle of speech', () => {
    const d = new EndpointDetector({ silenceMs: 1000 })
    const events = run(d, [
      [0.02, 300],
      [0.3, 600],
      [0.02, 600], // 息つぎ
      [0.3, 600],
    ])
    expect(events.map((e) => e[0])).toEqual(['speech'])
  })

  it('ignores short clicks and gives up when nobody speaks', () => {
    const d = new EndpointDetector({ silenceMs: 1000, noSpeechTimeoutMs: 3000 })
    const events = run(d, [
      [0.02, 300],
      [0.5, 100], // 物音
      [0.02, 4000],
    ])
    expect(events.map((e) => e[0])).toEqual(['no-speech'])
    expect(d.heardSpeech).toBe(false)
  })

  it('with a higher minimum threshold, ignores quieter sound (for barge-in)', () => {
    const d = new EndpointDetector({ silenceMs: 800, minThreshold: 0.15, minSpeechMs: 350, noSpeechTimeoutMs: Infinity })
    const events = run(d, [
      [0.02, 300],
      [0.1, 2000], // スピーカーから回り込んだ小さめの音
      [0.3, 400], // 話しかけられた
    ])
    expect(events.map((e) => e[0])).toEqual(['speech'])
  })

  it('adapts the threshold to background noise', () => {
    const d = new EndpointDetector({ silenceMs: 800 })
    // 雑音が大きい部屋では、雑音程度の音は声とみなさない
    const events = run(d, [
      [0.1, 300],
      [0.12, 1500],
      [0.4, 600],
      [0.1, 1000],
    ])
    expect(events.map((e) => e[0])).toEqual(['speech', 'end'])
    expect(d.threshold).toBeCloseTo(0.25)
  })
})
