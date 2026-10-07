'use client';
import {AppShell} from './app-shell';
import {TickerLink} from './ticker-link';
import {WatchButton} from './watch-button';
import {usePoll,useWatched} from '@/lib/use-market';
import type {WatchlistPage} from '@/lib/contracts';
import {money} from '@/lib/format';
import {pctText,tone} from '@/lib/market-format';
export function WatchlistPanel(){const {data,failed}=usePoll<WatchlistPage>('/watchlist',60000);
 const watched=useWatched();const items=data&&watched?data.items.filter(i=>watched.has(i.symbol)):data?.items;  // A star tapped here drops its row at once.
 return <AppShell><main id="main" className="workspace"><div className="page-head"><h1 tabIndex={-1}>Watchlist</h1><p>Your starred tickers with today’s price and change.</p></div>
 <section className="panel">{data===null?(failed?<p className="panel-empty">Couldn’t load right now. Retrying shortly.</p>:<div className="skeleton-list" aria-label="Loading"><span/><span/><span/></div>)
  :items!.length===0?<div className="empty-state"><p>Nothing on your watchlist yet.</p><p className="small">Tap the star next to a ticker on an alert, a trade setup or a ticker report to add it here.</p></div>
  :<><ul className="watch-list">{items!.map(i=><li key={i.symbol} className="watch-row"><TickerLink ticker={i.symbol} className="ticker"/>{i.new_alert&&<span className="pill pill-up" title="The bot posted an alert on this ticker in the last 24 hours">New alert</span>}
   <span className="watch-price">{i.price!=null?money(i.price):'—'}</span><span className={'watch-change '+tone(i.change_pct)}>{pctText(i.change_pct)}</span><WatchButton ticker={i.symbol}/></li>)}</ul>
   <p className="small watch-foot">{items!.length} of {data.limit} tickers. Prices update about once a minute.</p></>}
 </section></main></AppShell>}
