import 'katex/dist/katex.min.css'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { readableMath } from '../lib/mathText'

/**
 * AI の返事を、太字・箇条書き・コード・数式（LaTeX）つきで表示する。
 * HTML は表示しない（react-markdown は生の HTML を描画しない）。数式は KaTeX で描き、
 * 書きかけ・誤りのある数式はエラーにせず、そのまま表示する。
 */
export function MarkdownText({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: 'ignore', trust: false }]]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {readableMath(text)}
      </ReactMarkdown>
    </div>
  )
}
