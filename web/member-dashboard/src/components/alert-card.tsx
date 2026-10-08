'use client';
import {useId,useState} from 'react';
import {SourceCall} from './source-call';
import {TickerLink} from './ticker-link';
import {PriceTag} from './price-tag';
import {WatchButton} from './watch-button';
import type {LatestCard,TickerQuote} from '@/lib/contracts';
import {timeAgo} from '@/lib/format';
import {formatShort} from '@/lib/time';



/** One #alerts post: several analysts on the same ticker in a short time. */
export function AlertCard({card,now,quote}:{card:LatestCard;now:number;quote?:TickerQuote}){const g=card.group!;
 const count=(v:'bullish'|'bearish'|'unclear')=>g.calls.filter(c=>c.view===v).length;
 const up=count('bullish'),down=count('bearish');
 const fresh=now-card.observed_at<1800;
 const [open,setOpen]=useState(false),listId=useId();
 // The whole card opens the analysts' posts; links, buttons, the open list and selecting text keep their own behaviour.
 const toggle=(e:React.MouseEvent)=>{const t=e.target as HTMLElement;if(t.closest('a,button,.alert-calls')||window.getSelection()?.toString())return;setOpen(o=>!o);};
 // Only the calls that took a side are counted here; the unclear ones are still listed when the card is opened.
 const split=[up&&`${up} bullish`,down&&`${down} bearish`].filter(Boolean).join(', ');
 return <article className="alert" data-fresh={fresh||undefined} data-open={open||undefined} onClick={toggle}>
  <div className="alert-head">
   <TickerLink ticker={card.ticker} className="alert-ticker" tip={'Research '+card.ticker}/>
   <PriceTag price={card.price} quote={quote} className="alert-price"/>
   <WatchButton ticker={card.ticker}/>
   <time className="alert-time" dateTime={new Date(card.observed_at*1000).toISOString()} title={formatShort(card.observed_at)}>{fresh&&<span className="new-dot" aria-label="New"/>}{timeAgo(card.observed_at,now)}</time>
   <button type="button" className="alert-toggle" aria-expanded={open} aria-controls={listId} aria-label={(open?'Hide':'Show')+' what the '+g.calls.length+' analysts said'} onClick={()=>setOpen(o=>!o)}><svg className="calls-chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>
  </div>
  <div className="alert-sum"><p className="alert-line"><strong>{g.analysts} analysts</strong> posted within {g.span}{split&&<span className="alert-split"> · {split}</span>}</p>
   {up+down>0&&<span className="sentiment" aria-hidden="true"><span style={{width:Math.round(up/(up+down)*100)+'%'}}/></span>}</div>
  {open&&<ul className="alert-calls" id={listId}>{g.calls.map((c,i)=><li key={c.analyst} className="call"><span className="call-num" data-view={c.view} aria-hidden="true">{i+1}</span><div className="call-bubble"><SourceCall call={c}/></div></li>)}</ul>}
 </article>}
