import {z} from 'zod';
import type {LatestCard,TickerQuote} from './contracts';
import {money} from './format';
import {pctText} from './market-format';

export const directionLabels={bullish:'Bullish',bearish:'Bearish',neutral:'Neutral',unclear:'Unclear'};
export const columns=['price','change','direction','age','reason'] as const;
export type Column=typeof columns[number];
export const columnLabels:Record<Column,string>={price:'Price',change:'Day change',direction:'Source direction',age:'Source age',reason:'Match conditions'};
const bound=z.string().max(24);
export const filterSchema=z.strictObject({symbols:z.string().max(256),exclude:z.string().max(256),minPrice:bound,maxPrice:bound,minChange:bound,maxChange:bound,maxAge:bound,direction:z.enum(['all','bullish','bearish','neutral','unclear']),watched:z.boolean()});
export type Filters=z.infer<typeof filterSchema>;
export const emptyFilters:Filters={symbols:'',exclude:'',minPrice:'',maxPrice:'',minChange:'',maxChange:'',maxAge:'',direction:'all',watched:false};
export const screenSchema=z.strictObject({universe:z.enum(['setups','alerts']),filters:filterSchema,sort:z.enum(['symbol',...columns]),descending:z.boolean(),columns:z.array(z.enum(columns)).max(5).refine(c=>new Set(c).size===c.length),density:z.enum(['compact','comfortable'])});
export type Screen=z.infer<typeof screenSchema>;
export const defaultScreen:Screen={universe:'setups',filters:emptyFilters,sort:'age',descending:false,columns:[...columns],density:'compact'};
export const savedSchema=z.strictObject({version:z.literal(1),current:screenSchema,saved:z.array(z.strictObject({name:z.string().trim().min(1).max(60),screen:screenSchema})).max(20)});
export type Preferences=z.infer<typeof savedSchema>;
export type Candidate={card:LatestCard;quote:TickerQuote|null;age:number};
const numeric=(s:string)=>s.trim()===''?null:Number(s);
const symbolSet=(s:string)=>new Set(s.toUpperCase().split(/[\s,]+/).filter(Boolean));
export function validateFilters(f:Filters):string{
 for(const [key,label] of [['minPrice','Minimum price'],['maxPrice','Maximum price'],['minChange','Minimum day change'],['maxChange','Maximum day change'],['maxAge','Maximum source age']] as const){
  const raw=f[key].trim(),n=numeric(raw);
  if(raw&&(!/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(raw)||n==null||!Number.isFinite(n)))return label+' must be a finite number.';
  if(n!=null&&(['minPrice','maxPrice','maxAge'].includes(key))&&n<0)return label+' must be zero or greater.';
 }
 if(numeric(f.minPrice)!=null&&numeric(f.maxPrice)!=null&&numeric(f.minPrice)!>numeric(f.maxPrice)!)return 'Minimum price must not exceed maximum price.';
 if(numeric(f.minChange)!=null&&numeric(f.maxChange)!=null&&numeric(f.minChange)!>numeric(f.maxChange)!)return 'Minimum day change must not exceed maximum day change.';
 if(numeric(f.maxAge)!=null&&numeric(f.maxAge)!>168)return 'Maximum source age cannot exceed 168 hours (7 days).';
 for(const s of [...symbolSet(f.symbols),...symbolSet(f.exclude)])if(!/^[A-Z][A-Z0-9.\-]{0,15}$/.test(s))return 'Use stock symbols separated by spaces or commas.';
 if([...symbolSet(f.symbols)].some(s=>symbolSet(f.exclude).has(s)))return 'A symbol cannot be included and excluded at the same time.';
 return '';
}
export function candidates(cards:LatestCard[],quotes:TickerQuote[],now:number):Candidate[]{
 const prices=new Map(quotes.map(q=>[q.symbol,q]));const seen=new Set<string>();
 return [...cards].sort((a,b)=>b.observed_at-a.observed_at).flatMap(card=>{if(seen.has(card.ticker))return [];seen.add(card.ticker);return [{card,quote:prices.get(card.ticker)??null,age:Math.max(0,(now-card.observed_at)/3600)}];});
}
export function conditions(f:Filters):{key:keyof Filters;label:string;required:string}[]{
 const out:{key:keyof Filters;label:string;required:string}[]=[];
 const range=(low:string,high:string,format:(n:number)=>string)=>low&&high?format(Number(low))+'–'+format(Number(high)):low?'≥ '+format(Number(low)):'≤ '+format(Number(high));
 if(f.symbols.trim())out.push({key:'symbols',label:'Symbols',required:[...symbolSet(f.symbols)].join(', ')});
 if(f.exclude.trim())out.push({key:'exclude',label:'Exclude',required:[...symbolSet(f.exclude)].join(', ')});
 if(f.minPrice.trim()||f.maxPrice.trim())out.push({key:'minPrice',label:'Price',required:range(f.minPrice.trim(),f.maxPrice.trim(),money)});
 if(f.minChange.trim()||f.maxChange.trim())out.push({key:'minChange',label:'Day change',required:range(f.minChange.trim(),f.maxChange.trim(),pctText)});
 if(f.maxAge.trim())out.push({key:'maxAge',label:'Source age',required:'≤ '+Number(f.maxAge)+' h'});
 if(f.direction!=='all')out.push({key:'direction',label:'Source direction',required:directionLabels[f.direction]});
 if(f.watched)out.push({key:'watched',label:'Watchlist',required:'On your watchlist'});
 return out;
}
export function screenCandidates(rows:Candidate[],f:Filters,watched:Set<string>|null){
 const include=symbolSet(f.symbols),exclude=symbolSet(f.exclude);let missing=0;
 if(validateFilters(f))return {rows:[],missing,error:validateFilters(f)};
 const matched=rows.filter(r=>{
  if(include.size&&!include.has(r.card.ticker)||exclude.has(r.card.ticker)||f.direction!=='all'&&r.card.direction!==f.direction||f.watched&&!watched?.has(r.card.ticker))return false;
  if(f.maxAge.trim()&&r.age>Number(f.maxAge))return false;
  const price=r.quote?.price,change=r.quote?.change_pct;
  if((f.minPrice.trim()||f.maxPrice.trim())&&price==null||(f.minChange.trim()||f.maxChange.trim())&&change==null){missing++;return false;}
  if(f.minPrice.trim()&&price!<Number(f.minPrice)||f.maxPrice.trim()&&price!>Number(f.maxPrice))return false;
  if(f.minChange.trim()&&change!<Number(f.minChange)||f.maxChange.trim()&&change!>Number(f.maxChange))return false;
  return true;
 });
 return {rows:matched,missing,error:''};
}
export function sortCandidates(rows:Candidate[],sort:Screen['sort'],descending:boolean):Candidate[]{
 const value=(r:Candidate):number|string|null=>sort==='symbol'?r.card.ticker:sort==='price'?r.quote?.price??null:sort==='change'?r.quote?.change_pct??null:sort==='age'?r.age:sort==='direction'?directionLabels[r.card.direction]:r.card.ticker;
 return [...rows].sort((a,b)=>{const x=value(a),y=value(b);if(x==null)return y==null?a.card.ticker.localeCompare(b.card.ticker):1;if(y==null)return -1;const d=typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y));return (descending?-d:d)||a.card.ticker.localeCompare(b.card.ticker);});
}
