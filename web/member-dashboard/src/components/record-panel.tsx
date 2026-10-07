'use client';
import {AppShell} from './app-shell';
import {TickerLink} from './ticker-link';
import {usePoll} from '@/lib/use-market';
import type {RecordPage} from '@/lib/contracts';
import {formatShort} from '@/lib/time';
import {money} from '@/lib/format';
import {pctText,tone} from '@/lib/market-format';
const MIN=20;  // No rate on fewer alerts than this.
const rate=(up:number,count:number)=>count>=MIN?Math.round(up/count*100)+'% ('+up.toLocaleString('en-US')+' of '+count.toLocaleString('en-US')+')':count.toLocaleString('en-US')+' alerts, too few for a rate';
export function RecordPanel(){const {data,failed}=usePoll<RecordPage>('/record',300000);
 return <AppShell><main id="main" className="workspace"><div className="page-head"><h1 tabIndex={-1}>Track record</h1><p>How the bot’s own alerts did after they were posted. Alerts that never reached Discord are not counted.</p></div>
 {data===null?(failed?<p className="panel-empty">Couldn’t load right now. Retrying shortly.</p>:<div className="skeleton-list" aria-label="Loading"><span/><span/><span/></div>)
 :<><section className="panel record-summary"><header className="panel-head"><div><h2>Last {data.days} days</h2><p>{data.total.toLocaleString('en-US')} alerts. Favorable means up for bullish alerts and down for bearish alerts. Unknown directions are excluded from the rate.</p><p className="small">Price changes are stock moves, not trade returns. Older observations used spot quotes; missed one-day observations use the next trading close. Five days means five trading days.</p></div></header>
  <div className="record-grid">{data.horizons.map(h=><div key={h.key} className="record-card"><h3>After {h.label}</h3>
   {h.count===0?<p className="small">No later prices recorded yet.</p>:<>
   <p className="record-rate">{rate(h.favorable,h.graded)}</p><p className="small">moved in the alert’s direction{h.flat>0&&<>, {h.flat.toLocaleString('en-US')} prices unchanged</>}</p>{h.key==='1h'&&<p className="small">Only alerts posted while the market was open.</p>}
   <p className="record-median">Median price move <strong>{pctText(h.median_pct,1)}</strong></p>
   {h.spy_count>0?<p className="small">S&amp;P 500 over the same days: {h.spy_count>=MIN?Math.round(h.spy_up/h.spy_count*100)+'% up ('+h.spy_up.toLocaleString('en-US')+' of '+h.spy_count.toLocaleString('en-US')+')':'too few days for a rate'}, median <span className={tone(h.spy_median_pct,1)}>{pctText(h.spy_median_pct,1)}</span></p>:<p className="small">{h.key==='1h'?'No S&P 500 comparison for one hour (daily closes only).':'S&P 500 closes not available yet.'}</p>}</>}
   <p className="small">{h.pending.toLocaleString('en-US')} pending · {h.unavailable.toLocaleString('en-US')} later prices unavailable</p>
  </div>)}</div></section>
  <section className="panel record-recent"><header className="panel-head"><div><h2>Latest alerts</h2><p>The last {data.recent.length} alerts with actual price changes. Green follows the alert’s direction; red goes against it.</p></div></header>
   {data.recent.length===0?<p className="panel-empty">No alerts yet.</p>:<div className="record-table-wrap" role="region" aria-label="Alert outcomes, scroll for more columns" tabIndex={0}><table className="table record-table"><thead><tr><th>Alert</th><th>1 hour</th><th>1 day</th><th>5 days</th></tr></thead><tbody>{data.recent.map((r,i)=><tr key={i}><td><TickerLink ticker={r.ticker} className="ticker"/><span className="small record-when" title={formatShort(r.alerted_at)}>{r.direction} · {money(r.price)} · {formatShort(r.alerted_at)}</span></td>
    {[r.move_1h,r.move_1d,r.move_5d].map((m,j)=>{const status=[r.status_1h,r.status_1d,r.status_5d][j];return <td key={j} className={r.direction==='unclear'?'':tone(m==null?null:m*(r.direction==='bearish'?-1:1),1)}>{status==='recorded'?<>{pctText(m,1)}<small className="record-status">{r.direction==='unclear'?'Direction not recorded':[r.favorable_1h,r.favorable_1d,r.favorable_5d][j]===true?'Favorable':[r.favorable_1h,r.favorable_1d,r.favorable_5d][j]===false?'Adverse':'Unchanged'}</small></>:status==='closed'?'Market closed':status==='pending'?'Pending':'Unavailable'}</td>})}</tr>)}</tbody></table></div>}
  </section></>}
 </main></AppShell>}
