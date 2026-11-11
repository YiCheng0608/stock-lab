import { Link } from 'react-router-dom'

import { Card } from '../components/ui'

// 系統 (/system, Issue 631): the one footer entry to the pages that are not part of the daily reading, the news list
// among them since it left the main navigation. Static: the links and one line on what each page is for.
export const SYSTEM_LINKS: ReadonlyArray<{ to: string; label: string; description: string }> = [
  { to: '/news', label: '新聞', description: '全部國內、國際新聞與官方公告，含 AI 判讀；和個股有關的新聞也在個股頁的新聞分頁。' },
  { to: '/research/backtest', label: '技術回測', description: '突破與回踩規則在歷史資料上的模擬結果。' },
  { to: '/research/coverage', label: '資料覆蓋度', description: '各類資料收集到哪一天、哪些日子缺資料。' },
  { to: '/research/strategies', label: '策略版本', description: '規則與評分的版本和設定快照。' },
  { to: '/system/data-quality', label: '資料品質', description: '每日排程的執行紀錄、來源檢查與原始資料。' },
  { to: '/glossary', label: '用語表', description: '頁面上用到的名詞解釋。' },
]

export function SystemPage() {
  return (
    <div className="page system-page">
      <section className="page-title">
        <div className="eyebrow">資料與工具</div>
        <h1>系統</h1>
        <p>每天選股用不到、但想查資料來源或規則細節時會用到的頁面。</p>
      </section>
      <div className="glossary-grid system-links">
        {SYSTEM_LINKS.map((item) => (
          <Card key={item.to}>
            <h2><Link className="text-link" to={item.to}>{item.label}</Link></h2>
            <p className="muted">{item.description}</p>
          </Card>
        ))}
      </div>
    </div>
  )
}
