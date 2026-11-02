import { describe, expect, it } from 'vitest'
import { SSEParser } from './sse'

describe('SSEParser', () => {
  it('parses events split across chunks', () => {
    const p = new SSEParser<{ a: number }>()
    expect(p.feed('data: {"a"')).toEqual([])
    expect(p.feed(':1}\n\ndata: {"a":2}\n')).toEqual([{ a: 1 }])
    expect(p.feed('\n')).toEqual([{ a: 2 }])
  })

  it('handles CRLF and multibyte text', () => {
    const p = new SSEParser<{ t: string }>()
    expect(p.feed('data: {"t":"こんにちは"}\r\n\r\n')).toEqual([{ t: 'こんにちは' }])
  })
})
