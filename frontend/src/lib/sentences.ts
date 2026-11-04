const BOUNDARY = /[。！？!?\n…]+/g
const MAX_CHUNK = 120
/** 最初の読み上げを読点で区切るときの最小の長さ（短すぎると不自然な間になる） */
const EAGER_MIN = 8

/**
 * ストリーミングで届く応答を、読み上げ用に文単位で切り出す。
 * 文が完成した時点で読み上げを始められるので、応答全体を待たずに話し始められる。
 * eagerFirst を指定すると、最初の1つだけは読点（、）でも区切り、話し始めをさらに早める。
 */
export class SentenceChunker {
  private buffer = ''
  private emitted = false

  constructor(private readonly options: { eagerFirst?: boolean } = {}) {}

  push(text: string): string[] {
    const out = this.split(text).filter(hasSpeakableText)
    if (out.length) this.emitted = true
    return out
  }

  private split(text: string): string[] {
    this.buffer += text
    const out: string[] = []
    if (this.options.eagerFirst && !this.emitted && this.buffer.search(BOUNDARY) < 0) {
      const comma = this.buffer.indexOf('、', EAGER_MIN)
      if (comma > 0) {
        out.push(this.buffer.slice(0, comma + 1).trim())
        this.buffer = this.buffer.slice(comma + 1)
      }
    }
    let last = 0
    for (const match of this.buffer.matchAll(BOUNDARY)) {
      const end = match.index + match[0].length
      const sentence = this.buffer.slice(last, end).trim()
      if (sentence) out.push(sentence)
      last = end
    }
    this.buffer = this.buffer.slice(last)
    // 句点が来ないまま長くなった場合は読点で区切る
    while (this.buffer.length > MAX_CHUNK) {
      const cut = this.buffer.lastIndexOf('、', MAX_CHUNK)
      const at = cut > 0 ? cut + 1 : MAX_CHUNK
      out.push(this.buffer.slice(0, at).trim())
      this.buffer = this.buffer.slice(at)
    }
    return out
  }

  flush(): string[] {
    const rest = this.buffer.trim()
    this.buffer = ''
    return rest && hasSpeakableText(rest) ? [rest] : []
  }
}

function hasSpeakableText(text: string): boolean {
  return /[\p{L}\p{N}]/u.test(text)
}
