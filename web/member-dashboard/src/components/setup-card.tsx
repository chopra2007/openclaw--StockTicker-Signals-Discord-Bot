import {TickerLink} from './ticker-link';
import {PriceTag} from './price-tag';
import {WatchButton} from './watch-button';
import type {LatestCard,TickerQuote} from '@/lib/contracts';
import {money,timeAgo} from '@/lib/format';
import {formatShort} from '@/lib/time';
import {away,pctText} from '@/lib/market-format';
import {Direction} from './feed-card';
function Line({label,value,tone,pct}:{label:string;value:string;tone?:'up'|'down';pct:number|null}){return <div><dt>{label}</dt><dd className={tone}>{value}</dd><small>{pct==null?'':pctText(pct,1)}</small></div>}
/** Entry, stop and first target on one line each, with the distance from the current price; later targets behind a tap. */
export function SetupCard({card,quote}:{card:LatestCard;quote?:TickerQuote}){const p=card.plan!;const price=quote?.price??card.price;
 const zone=p.entry_low!=null&&p.entry_high!=null&&p.entry_low!==p.entry_high;const entryMid=zone?(p.entry_low!+p.entry_high!)/2:p.entry_low??p.entry_high??card.price;
 const entry=zone?money(p.entry_low)+' – '+money(p.entry_high):money(entryMid);
 return <article className="item"><div className="item-head"><TickerLink ticker={card.ticker} className="ticker"/><Direction value={p.direction}/><PriceTag price={card.price} quote={quote} className="item-price"/><WatchButton ticker={card.ticker}/>{card.score!=null&&<span className="pill pill-muted" title="Bot score, out of 100">Score {Math.round(card.score)}/100</span>}<span className="item-time" title={formatShort(card.observed_at)}>{timeAgo(card.observed_at)}</span></div>
 {card.text&&<p className="item-text">{card.text.replace(/^Sec filing$/i,'SEC filing')}</p>}
 <dl className="plan-lines"><Line label="Entry" value={entry} pct={away(entryMid,price)}/>{p.stop!=null&&<Line label="Stop" value={money(p.stop)} tone="down" pct={away(p.stop,price)}/>}{p.targets.length>0&&<Line label="Target 1" value={money(p.targets[0])} tone="up" pct={away(p.targets[0],price)}/>}</dl>
 {p.targets.length>1&&<details className="plan-more"><summary>{p.targets.length-1===1?'1 more target':(p.targets.length-1)+' more targets'}</summary><dl className="plan-lines">{p.targets.slice(1).map((t,i)=><Line key={i} label={'Target '+(i+2)} value={money(t)} tone="up" pct={away(t,price)}/>)}</dl></details>}</article>}
