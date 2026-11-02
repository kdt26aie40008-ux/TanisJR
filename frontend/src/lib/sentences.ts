const BOUNDARY = /[。！？!?\n…]+/g
const MAX_CHUNK = 120

/**
 * ストリーミングで届く応答を、読み上げ用に文単位で切り出す。
 * 文が完成した時点で読み上げを始められるので、応答全体を待たずに話し始められる。
 */
export class SentenceChunker {
  private buffer = ''

  push(text: string): string[] {
    this.buffer += text
    const out: string[] = []
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
    return out.filter(hasSpeakableText)
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
