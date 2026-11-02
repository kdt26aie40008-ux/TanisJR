import { BackupRestore } from '../components/BackupPanel'

/** 暗号鍵が読み込めない（別PC・Windows再インストール等）ときの画面。データは消さず、復元だけを提示する。 */
export function RestorePage({ reason, onRestored }: { reason: string; onRestored: () => void }) {
  return (
    <div className="setup">
      <div className="setup-card panel">
        <header className="setup-header">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          <h1>データがロックされています</h1>
        </header>
        <div className="banner warn" role="alert">
          {reason}
        </div>
        <p className="hint">
          保存データは暗号化されており、このPCの暗号鍵で読み込めない状態です。データは削除されていません。
          以前に作成したバックアップファイルとパスフレーズで復元してください。
        </p>
        <BackupRestore onRestored={onRestored} />
      </div>
    </div>
  )
}
