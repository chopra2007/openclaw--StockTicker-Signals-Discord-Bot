'use client';
import {useStrip} from '@/lib/use-market';
import {clockTime,level,pctText,signed,tone} from '@/lib/market-format';
/** S&P 500, Nasdaq, Dow, Russell 2000 and VIX with the day change. Scrolls sideways on a phone; hidden until quotes exist. */
export function MarketStrip(){const {data}=useStrip();if(!data||data.quotes.length===0)return null;
 return <section className="market-strip" aria-label="Market indexes"><ul>{data.quotes.map(q=><li key={q.symbol}><span className="ms-name">{q.label}</span><span className="ms-price">{level(q.price)}</span>
  <span className={'ms-change '+tone(q.change_pct)} title={q.change==null?undefined:signed(q.change)+' today'}>{pctText(q.change_pct)}</span></li>)}</ul>
  {data.quote_time!=null&&<p className="ms-time">As of {clockTime(data.quote_time)}</p>}</section>}
