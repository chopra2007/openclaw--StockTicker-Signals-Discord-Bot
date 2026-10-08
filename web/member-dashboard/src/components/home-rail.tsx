'use client';
import Link from 'next/link';
import {useId} from 'react';
import {usePoll} from '@/lib/use-market';
import type {RecordPage,WatchlistPage} from '@/lib/contracts';
import {money} from '@/lib/format';
import {pctText,tone} from '@/lib/market-format';
import {TickerLink} from './ticker-link';

/** Overview side column: the alerts' one-day track record as a gauge, then the first watchlist rows. */
export function HomeRail({record}:{record:boolean}){return <aside className="home-rail">{record&&<RecordGauge/>}<WatchMini/></aside>}

function RecordGauge(){const {data}=usePoll<RecordPage>('/record?rows=0',600000);const id=useId();const h=data?.horizons.find(x=>x.key==='1d');if(!data||!h)return null;
 const scored=h.graded>=20,share=scored?h.favorable/h.graded:null;
 const angle=Math.PI*(1-(share??0)),x=110+90*Math.cos(angle),y=112-90*Math.sin(angle);
 return <section className="rail-card gauge-card"><div className="rail-head"><h2>Track record</h2><Link href="/record">Details <span aria-hidden="true">›</span></Link></div>
  <svg viewBox="0 0 220 124" width="220" height="124" aria-hidden="true"><defs><linearGradient id={id} x1="0" x2="1"><stop offset="0" stopColor="#ff453a"/><stop offset=".5" stopColor="#ffd60a"/><stop offset="1" stopColor="#30d158"/></linearGradient></defs>
   <path d="M20 112A90 90 0 0 1 200 112" fill="none" stroke="var(--fill)" strokeWidth="14" strokeLinecap="round"/>
   {scored&&<><path d="M20 112A90 90 0 0 1 200 112" fill="none" stroke={`url(#${id})`} strokeWidth="14" strokeLinecap="round" opacity=".9"/><circle cx={x} cy={y} r="9" fill="#000" stroke="var(--label)" strokeWidth="4"/></>}</svg>
  {share!=null?<><p className="gauge-value">{Math.round(share*100)}%</p><p className="gauge-label">Moved the alert’s way a day later</p>
   <p className="gauge-note">Of {h.graded.toLocaleString('en-US')} alerts with a recorded direction in the last {data.days} days, {h.favorable.toLocaleString('en-US')} moved in the alert’s direction a day later.</p></>
  :<><p className="gauge-value gauge-empty">—</p><p className="gauge-note">Not enough graded alerts yet to show a score.</p></>}
 </section>}

function WatchMini(){const {data,failed}=usePoll<WatchlistPage>('/watchlist',60000);const items=data?.items.slice(0,8);
 return <section className="rail-card watch-mini"><div className="rail-head"><h2>Watchlist</h2><Link href="/watchlist">See all <span aria-hidden="true">›</span></Link></div>
  {!data?<p className="rail-empty">{failed?'Couldn’t load right now. Retrying shortly.':'Loading…'}</p>
  :items!.length===0?<p className="rail-empty">Tap the star next to a ticker to add it here.</p>
  :<ul>{items!.map(i=><li key={i.symbol}><TickerLink ticker={i.symbol} className="ticker"/><span className="wm-price">{i.price!=null?money(i.price):'—'}</span><span className={'chip-change '+tone(i.change_pct)}>{pctText(i.change_pct)}</span></li>)}</ul>}
 </section>}
