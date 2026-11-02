/** Server-Sent Events のテキストを逐次パースする（チャンク境界をまたいでも動作する）。 */
export class SSEParser<T> {
  private buffer = ''

  feed(text: string): T[] {
    this.buffer += text.replace(/\r\n/g, '\n')
    const events: T[] = []
    let sep = this.buffer.indexOf('\n\n')
    while (sep >= 0) {
      const block = this.buffer.slice(0, sep)
      this.buffer = this.buffer.slice(sep + 2)
      const data = block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (data) events.push(JSON.parse(data) as T)
      sep = this.buffer.indexOf('\n\n')
    }
    return events
  }
}
