import { describe, expect, it } from 'vitest'
import { detectEmotion } from './emotion'
import { SentenceChunker } from './sentences'

describe('SentenceChunker', () => {
  it('emits sentences as soon as they are complete', () => {
    const c = new SentenceChunker()
    expect(c.push('こんにち')).toEqual([])
    expect(c.push('は。元気')).toEqual(['こんにちは。'])
    expect(c.push('ですか？　よかった！')).toEqual(['元気ですか？', 'よかった！'])
    expect(c.push('じゃあね')).toEqual([])
    expect(c.flush()).toEqual(['じゃあね'])
  })

  it('splits long text without a period at a comma', () => {
    const c = new SentenceChunker()
    const long = 'あ'.repeat(80) + '、' + 'い'.repeat(60)
    const out = c.push(long)
    expect(out[0]).toBe('あ'.repeat(80) + '、')
    expect(c.flush()).toEqual(['い'.repeat(60)])
  })

  it('with eagerFirst, starts speaking at the first comma only', () => {
    const c = new SentenceChunker({ eagerFirst: true })
    expect(c.push('うーん、')).toEqual([]) // 短すぎる区切りは待つ
    expect(c.push('それはちょっと違うと思うな、だって')).toEqual(['うーん、それはちょっと違うと思うな、'])
    // 2つ目以降は文の終わりまで待つ
    expect(c.push('昨日は、')).toEqual([])
    expect(c.push('晴れてたよ。')).toEqual(['だって昨日は、晴れてたよ。'])
  })

  it('with eagerFirst, prefers a complete sentence', () => {
    const c = new SentenceChunker({ eagerFirst: true })
    expect(c.push('そうなんだ、それは良かったね。')).toEqual(['そうなんだ、それは良かったね。'])
  })

  it('skips punctuation-only chunks', () => {
    const c = new SentenceChunker()
    expect(c.push('。。！\n')).toEqual([])
  })
})

describe('detectEmotion', () => {
  it.each([
    ['合格おめでとう！本当に嬉しいよ！', 'happy'],
    ['それは残念だったね。つらかったでしょう。', 'sad'],
    ['えっ、まさか本当に？', 'surprised'],
    ['了解です。', 'neutral'],
  ])('%s → %s', (text, emotion) => {
    expect(detectEmotion(text)).toBe(emotion)
  })
})
