import {TickerLink} from './ticker-link';
import type {LatestCard} from '@/lib/contracts';
import {money,timeAgo} from '@/lib/format';
import {formatWhen} from '@/lib/time';

const VIEW={bullish:'Bullish',bearish:'Bearish',unclear:'Unclear'} as const;

/** One #alerts post: several analysts on the same ticker in a short time. */
export function AlertCard({card,now}:{card:LatestCard;now:number}){const g=card.group!;
 const count=(v:'bullish'|'bearish'|'unclear')=>g.calls.filter(c=>c.view===v).length;
 const up=count('bullish'),down=count('bearish'),open=count('unclear'),total=g.calls.length||1;
 const fresh=now-card.observed_at<1800;
 const split=[up&&`${up} bullish`,down&&`${down} bearish`,open&&`${open} unclear`].filter(Boolean).join(', ');
 return <article className="alert" data-fresh={fresh||undefined}>
  <div className="alert-head">
   <TickerLink ticker={card.ticker} className="alert-ticker"/>
   {card.price!=null&&<span className="alert-price">{money(card.price)}</span>}
   <time className="alert-time" dateTime={new Date(card.observed_at*1000).toISOString()} title={timeAgo(card.observed_at,now)}>{fresh&&<span className="new-dot" aria-label="New"/>}{formatWhen(card.observed_at,now*1000)}</time>
  </div>
  <p className="alert-line"><strong>{g.analysts} analysts</strong> posted about {card.ticker} within {g.span}</p>
  <div className="vote" role="img" aria-label={split}>
   {up>0&&<span className="vote-up" style={{flexGrow:up/total}}/>}{down>0&&<span className="vote-down" style={{flexGrow:down/total}}/>}{open>0&&<span className="vote-open" style={{flexGrow:open/total}}/>}
  </div>
  <p className="vote-label">{split}</p>
  <details className="alert-calls"><summary>What they said</summary>
   <ul>{g.calls.map(c=><li key={c.analyst}><span className={'view view-'+c.view}>{VIEW[c.view]}</span><span className="who">@{c.analyst}</span><p className={c.reason==='reason not stated'?'no-reason':undefined}>{c.reason==='reason not stated'?'No reason given':c.reason}</p></li>)}</ul>
  </details>
 </article>}
