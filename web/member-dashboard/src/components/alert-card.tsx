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
 // Only the calls that took a side are counted here; the unclear ones are still listed under "What they said".
 const split=[up&&`${up} bullish`,down&&`${down} bearish`].filter(Boolean).join(', ');
 return <article className="alert" data-fresh={fresh||undefined}>
  <div className="alert-head">
   <TickerLink ticker={card.ticker} className="alert-ticker"/>
   <PriceTag price={card.price} quote={quote} className="alert-price"/>
   <WatchButton ticker={card.ticker}/>
   <time className="alert-time" dateTime={new Date(card.observed_at*1000).toISOString()} title={formatShort(card.observed_at)}>{fresh&&<span className="new-dot" aria-label="New"/>}{timeAgo(card.observed_at,now)}</time>
  </div>
  <div className="alert-sum"><p className="alert-line"><strong>{g.analysts} analysts</strong> posted within {g.span}{split&&<span className="alert-split"> · {split}</span>}</p>
   {up+down>0&&<span className="sentiment" aria-hidden="true"><span style={{width:Math.round(up/(up+down)*100)+'%'}}/></span>}</div>
  <details className="alert-calls"><summary>What they said</summary>
   <ul>{g.calls.map(c=><li key={c.analyst}><SourceCall call={c}/></li>)}</ul>
  </details>
 </article>}
