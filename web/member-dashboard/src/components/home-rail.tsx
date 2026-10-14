'use client';
import Link from 'next/link';
import {usePoll} from '@/lib/use-market';
import type {WatchlistPage} from '@/lib/contracts';
import {money} from '@/lib/format';
import {pctText,tone} from '@/lib/market-format';
import {TickerLink} from './ticker-link';

/** Overview side column: the first watchlist rows. */
export function HomeRail(){return <aside className="home-rail"><WatchMini/></aside>}

function WatchMini(){const {data,failed}=usePoll<WatchlistPage>('/watchlist',60000);const items=data?.items.slice(0,8);
 return <section className="rail-card watch-mini"><div className="rail-head"><h2>Watchlist</h2><Link href="/watchlist">See all <span aria-hidden="true">›</span></Link></div>
  {!data?<p className="rail-empty">{failed?'Couldn’t load right now. Retrying shortly.':'Loading…'}</p>
  :items!.length===0?<p className="rail-empty">Tap the star next to a ticker to add it here.</p>
  :<ul>{items!.map(i=><li key={i.symbol}><TickerLink ticker={i.symbol} className="ticker"/><span className="wm-price">{i.price!=null?money(i.price):'—'}</span><span className={'chip-change '+tone(i.change_pct)}>{pctText(i.change_pct)}</span></li>)}</ul>}
 </section>}
