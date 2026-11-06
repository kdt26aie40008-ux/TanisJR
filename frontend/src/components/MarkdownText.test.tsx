import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarkdownText } from './MarkdownText'

describe('MarkdownText', () => {
  it('renders formulas with KaTeX instead of raw LaTeX', () => {
    const { container } = render(
      <MarkdownText text={'解の公式は $$ x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a} $$ だよ。\n\n方程式 $ ax^2 + bx + c = 0 $ を解く。'} />,
    )
    expect(container.querySelectorAll('.katex').length).toBe(2)
    // 画面に見える部分（読み上げ用に隠れている MathML の元の式を除く）に LaTeX の記号が出ない
    container.querySelectorAll('.katex-mathml').forEach((e) => e.remove())
    expect(container.textContent).not.toContain('\\frac')
    expect(container.textContent).not.toContain('$')
  })

  it('renders bold, lists and code, but never raw HTML', () => {
    const { container } = render(
      <MarkdownText text={'**大事**なこと\n\n- 1つ目\n- 2つ目\n\n`code`\n\n<img src=x onerror="alert(1)">'} />,
    )
    expect(screen.getByText('大事').tagName).toBe('STRONG')
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('code')?.textContent).toBe('code')
    expect(container.querySelector('img')).toBeNull()
  })

  it('shows a broken formula as text instead of failing', () => {
    const { container } = render(<MarkdownText text={'途中の式 $\\frac{1}{$'} />)
    expect(container.textContent).toContain('途中の式')
  })
})
