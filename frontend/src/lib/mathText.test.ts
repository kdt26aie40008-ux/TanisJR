import { describe, expect, it } from 'vitest'
import { normalizeMath, readableMath, SpeechFilter, speakFormula, toSpeech } from './mathText'

describe('normalizeMath', () => {
  it('turns \\( \\) and \\[ \\] into dollar delimiters', () => {
    expect(normalizeMath('式は \\(x^2\\) です')).toBe('式は $x^2$ です')
    expect(normalizeMath('\\[ a+b \\]')).toContain('$$\na+b\n$$')
  })

  it('puts one-line $$ … $$ on its own block and trims spaces inside $ … $', () => {
    expect(normalizeMath('答えは $$ \\frac{x^3}{3} $$ だよ')).toContain('\n$$\n\\frac{x^3}{3}\n$$\n')
    expect(normalizeMath('方程式 $ ax^2 + bx + c = 0 $ の解')).toBe('方程式 $ax^2 + bx + c = 0$ の解')
  })

  it('leaves prices and plain text alone', () => {
    expect(normalizeMath('これは 100 円です')).toBe('これは 100 円です')
  })
})

describe('speakFormula', () => {
  it('reads fractions, roots and powers in Japanese', () => {
    expect(speakFormula('x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}')).toBe(
      'x イコール 2aぶんの ひく b プラスマイナス ルートbの2じょう ひく 4ac',
    )
    expect(speakFormula('\\int x^2 \\, dx = \\frac{x^3}{3} + C')).toBe(
      'インテグラル xの2じょう ディーx イコール 3ぶんのxの3じょう たす C',
    )
  })

  it('reads multi-digit and negative powers as one number', () => {
    // 「^22」を「の2乗 2」と読んでいた
    expect(speakFormula('x^22')).toBe('xの22じょう')
    expect(speakFormula('2^{10}')).toBe('2の10じょう')
    expect(speakFormula('x^{-1}')).toBe('xのマイナス1じょう')
  })

  it('reads integral and sum bounds as a range, not as powers', () => {
    expect(speakFormula('\\int_0^1 x^2 dx')).toBe('0から1までの積分 xの2じょう ディーx')
    expect(speakFormula('\\int_{0}^{\\infty} e^{-x}\\,dx')).toBe('0から 無限大 までの積分 eのマイナスxじょう ディーx')
    expect(speakFormula('\\sum_{k=1}^{n} k')).toBe('k イコール 1からnまでの和 k')
  })
})

describe('readableMath', () => {
  it('draws inline integrals and fractions at full size, with a space before dx', () => {
    expect(readableMath('答えは $\\int_0^1 x^2dx$ だよ')).toBe('答えは $\\displaystyle \\int_0^1 x^2\\,dx$ だよ')
    expect(readableMath('$\\frac{1}{2}$')).toBe('$\\displaystyle \\frac{1}{2}$')
    // ふつうの数式・別行の数式はそのまま
    expect(readableMath('$x^2$ と $$\\int x$$')).toBe('$x^2$ と \n$$\n\\int x\n$$\n')
  })
})

describe('SpeechFilter', () => {
  it('skips code blocks that span several sentences', () => {
    const f = new SpeechFilter()
    const spoken = ['例えばこう書くよ。', '```python', 'my_list.reverse()', '```', 'これで逆順になる。'].map((s) => f.next(s))
    expect(spoken).toEqual(['例えばこう書くよ。', '', '', '', 'これで逆順になる。'])
  })
})

describe('toSpeech', () => {
  it('reads formulas and drops markdown symbols and code', () => {
    const text = '公式は **$a^2 + b^2 = c^2$** だよ。\n```python\nprint(1)\n```\n`reverse()` を使う'
    const spoken = toSpeech(text)
    expect(spoken).toContain('aの2じょう たす bの2じょう イコール cの2じょう')
    expect(spoken).not.toMatch(/[$*`\\]|print/)
    expect(spoken).toContain('reverse() を使う')
  })

  it('reads powers written outside formulas', () => {
    expect(toSpeech('x²+y²=r²')).toBe('xの2じょう+yの2じょう=rの2じょう')
    expect(toSpeech('2^22 は大きい')).toBe('2の22じょう は大きい')
    expect(toSpeech('10⁻³ m')).toBe('10のマイナス3じょう m')
  })
})
