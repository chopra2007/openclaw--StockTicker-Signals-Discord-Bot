'use client';
import {useState} from 'react';
import type {Chart,Quote} from '@/lib/contracts';
import {formatShort} from '@/lib/time';
import {money,signedMoney,signedPct,tone} from '@/lib/format';
type Point=readonly [number,number];
export type ChartLevel={label:string;low:number;high?:number;kind:'zone'|'stop'|'target'};
const RANGES=['1D','5D','1M','6M','1Y'] as const;
type Range=typeof RANGES[number];
const DAILY_POINTS:Record<'1M'|'6M'|'1Y',number>={'1M':22,'6M':126,'1Y':252};
const dayKeyFormat=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'});
const dayLabelFormat=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',year:'numeric'});
const dayKey=(epoch:number)=>dayKeyFormat.format(new Date(epoch*1000));
function seriesFor(chart:Chart|null|undefined,range:Range):Point[]{
 if(!chart)return [];
 if(range==='5D')return chart.intraday;
 if(range==='1D'){const last=chart.intraday.at(-1);return last?chart.intraday.filter(p=>dayKey(p[0])===dayKey(last[0])):[];}
 return chart.daily.slice(-DAILY_POINTS[range]);
}
const clamp=(v:number,lo:number,hi:number)=>Math.min(hi,Math.max(lo,v));

/** Hero (price, day change, after hours) + the Apple-Stocks-style chart: green or red with the move, range tabs,
 *  drag a finger or the mouse along it to read the price and the date under it. Inline SVG, no chart library. */
export function PriceChart({ticker,quote,chart,levels,fallbackPrice}:{ticker:string;quote:Quote|null|undefined;chart:Chart|null|undefined;levels:ChartLevel[];fallbackPrice:number|null}){
 const [picked,setPicked]=useState<Range|null>(null),[hover,setHover]=useState<number|null>(null);
 const available=RANGES.filter(r=>seriesFor(chart,r).length>=2);
 const range=picked&&available.includes(picked)?picked:available[0]??null;
 const points=range?seriesFor(chart,range):[];
 const price=quote?.price??fallbackPrice;
 const previous=quote?.previous_close??null;
 const n=points.length,at=hover!=null&&hover<n?points[hover]:null;
 const first=range==='1D'&&previous?previous:points[0]?.[1],last=points.at(-1)?.[1];
 const rising=first!=null&&last!=null?last>=first:true;
 // Value range: the line (plus the previous close on 1D). A trade level only shows when it already sits inside it.
 const values=points.map(p=>p[1]).concat(range==='1D'&&previous?[previous]:[]);
 let lo=Math.min(...values),hi=Math.max(...values);const pad=(hi-lo)*.08||hi*.01;lo-=pad;hi+=pad;
 const y=(v:number)=>(hi-v)/(hi-lo)*100,x=(i:number)=>i/(n-1)*100;
 const inside=(v:number)=>v>=lo&&v<=hi;
 const path=points.map((p,i)=>(i?'L':'M')+x(i).toFixed(2)+' '+y(p[1]).toFixed(2)).join('');
 const shown=levels.filter(l=>inside(l.low)||(l.high!=null&&inside(l.high)));
 // Label position (% of the plot height), kept inside the plot so it never spills over the range tabs: a zone label is centred on its band, the others sit just above their line.
 const mark=(l:ChartLevel)=>l.high!=null?clamp(y((l.low+l.high)/2),6,94):clamp(y(l.low),10,98);
 const tags=[...shown].sort((a,b)=>mark(a)-mark(b)).reduce<ChartLevel[]>((kept,l)=>kept.length&&Math.abs(mark(l)-mark(kept[kept.length-1]))<9?kept:[...kept,l],[]);
 function move(e:React.PointerEvent<HTMLDivElement>){const box=e.currentTarget.getBoundingClientRect();if(box.width>0)setHover(clamp(Math.round((e.clientX-box.left)/box.width*(n-1)),0,n-1));}
 const when=at?(range==='1D'||range==='5D'?formatShort(at[0]):dayLabelFormat.format(new Date(at[0]*1000))):'';
 const shownPrice=at?at[1]:price;
 return <section className="rp-hero" aria-label={ticker+' price and chart'}>
  <p className="rp-price">{shownPrice!=null?money(shownPrice):''}</p>
  {at?<p className="rp-change rp-when">{when}</p>:quote?.change!=null&&quote.change_pct!=null?<p className={'rp-change '+tone(quote.change)}>{signedMoney(quote.change)} ({signedPct(quote.change_pct)}) today</p>:null}
  {!at&&quote?.ext_price!=null&&quote.ext_change!=null&&quote.ext_change_pct!=null&&<p className="rp-ext">{quote.ext_label||'After hours'} {money(quote.ext_price)} <span className={tone(quote.ext_change)}>{signedMoney(quote.ext_change)} ({signedPct(quote.ext_change_pct)})</span></p>}
  {range&&<>
   <div className="rp-chart" onPointerDown={e=>{e.currentTarget.setPointerCapture?.(e.pointerId);move(e);}} onPointerMove={move} onPointerUp={()=>setHover(null)} onPointerCancel={()=>setHover(null)} onPointerLeave={()=>setHover(null)}
    role="img" aria-label={`${ticker} price chart, ${range==='1D'?'last trading day':range==='5D'?'last 5 trading days':range==='1M'?'1 month':range==='6M'?'6 months':'1 year'}: from ${money(points[0][1])} to ${money(points[n-1][1])}`}>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
     {shown.filter(l=>l.kind==='zone'&&l.high!=null).map(l=>{const top=clamp(y(l.high!),0,100),bottom=clamp(y(l.low),0,100);return <rect key={l.label} className="rp-zone" x="0" width="100" y={top} height={Math.max(bottom-top,.6)}/>;})}
     {range==='1D'&&previous&&inside(previous)&&<line className="rp-prev" x1="0" x2="100" y1={y(previous)} y2={y(previous)}/>}
     {shown.filter(l=>l.kind!=='zone').map(l=><line key={l.label} className={'rp-level rp-level-'+l.kind} x1="0" x2="100" y1={y(l.low)} y2={y(l.low)}/>)}
     <path className={'rp-area '+(rising?'rp-up':'rp-down')} d={path+`L100 100L0 100Z`}/>
     <path className={'rp-line '+(rising?'rp-up':'rp-down')} d={path}/>
    </svg>
    {tags.map(l=><span key={l.label} className={'rp-tag rp-tag-'+l.kind} style={{top:mark(l)+'%'}}>{l.label} {l.high!=null?money(l.low)+'–'+money(l.high):money(l.low)}</span>)}
    {at&&hover!=null&&<><span className="rp-cursor" style={{left:x(hover)+'%'}}/><span className={'rp-dot '+(rising?'rp-up':'rp-down')} style={{left:x(hover)+'%',top:y(at[1])+'%'}}/></>}
   </div>
   <div className="rp-tabs" role="group" aria-label="Chart range">{available.map(r=><button key={r} type="button" aria-pressed={r===range} onClick={()=>{setPicked(r);setHover(null);}}>{r}</button>)}</div></>}
 </section>}
