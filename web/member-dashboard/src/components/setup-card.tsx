import {TickerLink} from './ticker-link';
import {PriceTag} from './price-tag';
import {WatchButton} from './watch-button';
import type {LatestCard,TickerQuote} from '@/lib/contracts';
import {money,timeAgo} from '@/lib/format';
import {formatShort} from '@/lib/time';
import {away,pctText} from '@/lib/market-format';
import {Direction} from './feed-card';
function Line({label,value,tone,pct,className}:{label:string;value:string;tone?:'up'|'down';pct:number|null;className?:string}){return <div className={className}><dt>{label}</dt><dd className={tone}>{value}</dd><small>{pct==null?'':pctText(pct,1)}</small></div>}
/** Stop, entry zone, current price and last target on one bar: red is the risk side, green the reward side. */
function Ladder({stop,low,high,price,target,short}:{stop:number|null;low:number|null;high:number|null;price:number|null;target:number|null;short:boolean}){
 if(stop==null||low==null||high==null||target==null)return null;
 const pts=[stop,low,high,target,...(price==null?[]:[price])],min=Math.min(...pts),max=Math.max(...pts);if(max===min)return null;
 const at=(v:number)=>((short?max-v:v-min)/(max-min))*100,a=Math.min(at(low),at(high)),b=Math.max(at(low),at(high));
 return <div className="ladder" aria-hidden="true"><span className="ladder-risk" style={{width:a+'%'}}/><span className="ladder-reward" style={{left:b+'%'}}/><span className="ladder-entry" style={{left:a+'%',width:Math.max(b-a,1.5)+'%'}}/>{price!=null&&<span className="ladder-now" style={{left:at(price)+'%'}}><small>now</small></span>}</div>}
/** Entry and stop on the first row, every target on the second, each with its distance from the current price. */
export function SetupCard({card,quote}:{card:LatestCard;quote?:TickerQuote}){const p=card.plan!;const price=quote?.price??card.price;
 const zone=p.entry_low!=null&&p.entry_high!=null&&p.entry_low!==p.entry_high;const entryMid=zone?(p.entry_low!+p.entry_high!)/2:p.entry_low??p.entry_high??card.price;
 const entry=zone?money(p.entry_low)+' – '+money(p.entry_high):money(entryMid),entryAway=away(entryMid,price);
 return <article className="item"><div className="item-head"><TickerLink ticker={card.ticker} className="ticker"/><Direction value={p.direction}/><PriceTag price={card.price} quote={quote} className="item-price"/><WatchButton ticker={card.ticker}/>{card.score!=null&&<span className="confidence" data-level={card.score>=70?'high':card.score>=50?'mid':'low'} title="How confident the bot is in this setup">Confidence <b>{Math.round(card.score)}%</b></span>}<span className="item-time" title={formatShort(card.observed_at)}>{timeAgo(card.observed_at)}</span></div>
 {card.text&&<p className="item-text">{card.text.replace(/^Sec filing$/i,'SEC filing')}</p>}
 <Ladder stop={p.stop} low={zone?p.entry_low!:entryMid} high={zone?p.entry_high!:entryMid} price={price} target={p.targets.at(-1)??null} short={p.direction==='short'}/>
 <dl className="plan-lines plan-grid"><div className="pg-entry"><dt>Entry</dt><dd>{entry}</dd><small>{entryAway==null?'':pctText(entryAway,1)}</small></div>{p.stop!=null&&<Line label="Stop" value={money(p.stop)} tone="down" pct={away(p.stop,price)}/>}
  {p.targets.map((t,i)=><Line key={i} label={'Target '+(i+1)} value={money(t)} tone="up" pct={away(t,price)} className={i===0?'pg-first':undefined}/>)}</dl></article>}
