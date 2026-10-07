import {TickerLink} from './ticker-link';
import type {LatestCard} from '@/lib/contracts';
import {sourceLabel,timeAgo} from '@/lib/format';
import {formatShort} from '@/lib/time';
export function Direction({value}:{value:string}){if(value==='unclear')return null;const label={bullish:'Bullish',bearish:'Bearish',long:'Long',short:'Short',neutral:'Neutral',unclear:'Mixed'}[value]||value;
 const tone=value==='bullish'||value==='long'?'up':value==='bearish'||value==='short'?'down':'flat';return <span className={'pill pill-'+tone}>{label}</span>}
export function FeedCard({card}:{card:LatestCard}){const who=sourceLabel(card.url);
 return <article className="item"><div className="item-head"><TickerLink ticker={card.ticker} className="ticker"/><Direction value={card.direction}/><span className="item-time" title={formatShort(card.observed_at)}>{timeAgo(card.observed_at)}</span></div>
 <p className="item-text">{card.text}</p>{who&&<p className="item-source">{card.url?<a href={card.url} target="_blank" rel="noreferrer noopener">{who} ↗</a>:who}</p>}</article>}
