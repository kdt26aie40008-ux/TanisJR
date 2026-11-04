import type { AppSettings } from '../api/types'

type BehaviorKey =
  | 'behavior_nod'
  | 'behavior_gaze'
  | 'behavior_backchannel'
  | 'behavior_barge_in'
  | 'behavior_sentence_emotion'

const ITEMS: { key: BehaviorKey; label: string; hint: string }[] = [
  { key: 'behavior_nod', label: '聞いている間うなずく', hint: 'あなたが話している間、声に合わせてうなずきます。' },
  { key: 'behavior_gaze', label: '目線をこちらに向ける', hint: 'こちらを見て、マウスの動きを目で追います。' },
  { key: 'behavior_backchannel', label: '相づちを入れる', hint: '声で話し終えたとき、考える前に「うん」などと短く返します。' },
  {
    key: 'behavior_sentence_emotion',
    label: '文ごとに表情を変える',
    hint: '話している内容に合わせて、文ごとに表情を変えます。',
  },
  {
    key: 'behavior_barge_in',
    label: '話の途中で割り込める',
    hint: '声で会話している間、話している途中でもあなたが話し始めたら止まって聞きます。スピーカーの音をマイクが拾うと勝手に止まることがあるため、ヘッドホンでの利用をおすすめします。',
  },
]

interface Props {
  settings: AppSettings
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void
}

/** 設定「ふるまい」: 会話の自然さに関わる動きを、1つずつオン・オフする */
export function BehaviorSettings({ settings, update }: Props) {
  return (
    <ul className="behavior-list">
      {ITEMS.map((item) => (
        <li key={item.key}>
          <label className={`switch${settings[item.key] ? ' on' : ''}`}>
            <input
              type="checkbox"
              role="switch"
              checked={settings[item.key]}
              onChange={(e) => update(item.key, e.target.checked)}
            />
            <span className="switch-track" aria-hidden />
            <span className="behavior-label">{item.label}</span>
          </label>
          <p className="hint">{item.hint}</p>
        </li>
      ))}
    </ul>
  )
}
