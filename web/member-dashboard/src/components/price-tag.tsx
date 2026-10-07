import type {TickerQuote} from '@/lib/contracts';
import {money} from '@/lib/format';
import {pctText,tone} from '@/lib/market-format';
/** Current price with its day change when the market snapshot has the ticker; otherwise the price the card was made at. */
export function PriceTag({price,quote,className}:{price:number|null;quote?:TickerQuote;className?:string}){const shown=quote?.price??price;if(shown==null)return null;
 return <span className={className}><span title={quote?.price!=null?'Current price':'Price when the card was made'}>{money(shown)}</span>{quote?.change_pct!=null&&<span className={'day-change '+tone(quote.change_pct)} title="Change today">{pctText(quote.change_pct)}</span>}</span>}
