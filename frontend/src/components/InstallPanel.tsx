import { useEffect, useState } from 'react'
import { canInstall, isStandalone, onInstallChange, promptInstall } from '../lib/install'

/** 設定「アプリのように開く」（PWA としてインストール。追加のダウンロードは不要） */
export function InstallPanel() {
  const [, setTick] = useState(0)
  const [result, setResult] = useState('')
  useEffect(() => onInstallChange(() => setTick((t) => t + 1)), [])

  const standalone = isStandalone()
  return (
    <div className="panel">
      <h2>アプリのように開く</h2>
      {standalone ? (
        <p>いまはアプリとして開いています。タスクバーやスタートメニューから、いつでもこの画面を開けます。</p>
      ) : (
        <>
          <p className="hint">
            ブラウザーのタブではなく、専用のウィンドウで開けるようになります。デスクトップ・スタートメニュー・タスクバーから起動できます。
            追加のダウンロードはありません（アプリの画面は、この PC のサーバーから読み込みます）。
          </p>
          {canInstall() ? (
            <div className="actions wrap">
              <button
                className="btn primary"
                onClick={() =>
                  void promptInstall().then((ok) => setResult(ok ? 'インストールしました。' : 'インストールをやめました。'))
                }
              >
                アプリとしてインストール
              </button>
            </div>
          ) : (
            <ol className="guide">
              <li>Edge または Chrome でこの画面を開きます。</li>
              <li>アドレスバーの右端にある「アプリをインストール」のアイコン、またはメニュー（…）の「アプリ」→「このサイトをアプリとしてインストール」を選びます。</li>
            </ol>
          )}
          {result && (
            <p className="ok-text" role="status">
              {result}
            </p>
          )}
          <p className="hint">サーバー（start.bat またはバックグラウンドサービス）が動いているときだけ開けます。</p>
        </>
      )}
    </div>
  )
}
