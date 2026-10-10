'use client';
import {useEffect,useRef,useState} from 'react';
import type {Evidence,Quote,SectionResult} from '@/lib/contracts';
import {formatShort,formatDay} from '@/lib/time';
import {compact,money,parseNote,signedPct,sourceLabel,timeAgo,type NotePoint} from '@/lib/format';
import {SafeLink} from './research-details';
import {ExpectedMove} from './expected-move';
type Payload=NonNullable<SectionResult['payload']>;
const titles:Record<SectionResult['section'],string>={analysis:'Analysis',em_daily:'Expected move',em_weekly:'Expected move',options:'Options activity',sec:'SEC filings'};
export type AnalysisPayload=Extract<Payload,{kind:'analysis'}>;
type OptionsPayload=Extract<Payload,{kind:'options'}>;
type SecPayload=Extract<Payload,{kind:'sec'}>;
const level=(p:AnalysisPayload,name:string)=>p.levels.find(l=>l.label===name);

/** One grouped list: a heading above a rounded block, like iOS Settings. */
export function Group({title,note,className,children}:{title:string;note?:string;className?:string;children:React.ReactNode}){
 return <section className={'rp-group '+(className||'')} aria-label={title}><h2>{title}</h2>{note&&<p className="rp-note">{note}</p>}{children}</section>}

export const unavailable:Record<string,string>={em_daily:'Not available right now. Option prices are too thin, usually outside market hours.',em_weekly:'Not available right now. Option prices are too thin, usually outside market hours.',options:'No options data right now.',analysis:'Analysis isn’t available right now. Try Refresh in a minute.',sec:'SEC filings aren’t available right now.'};
/** A report section as its own group, with the loading and unavailable states handled once. */
export function ReportGroup({result,title,className,children}:{result:SectionResult;title:string;className?:string;children:(p:Payload)=>React.ReactNode}){
 const busy=['queued','running'].includes(result.status),p=result.payload;
 return <Group title={title} className={className}>{busy&&!p?<div className="skeleton-list"><span/><span/></div>:p?children(p):<p className="quiet">{result.section==='sec'&&result.message?result.message:unavailable[result.section]}</p>}</Group>}

/** A catalyst or risk: two lines, tap to read the rest. */
function ClampPoint({point,expandAll}:{point:NotePoint;expandAll:boolean}){const [open,setOpen]=useState(false),[truncated,setTruncated]=useState(false);const body=useRef<HTMLSpanElement>(null);const expanded=expandAll||open;
 useEffect(()=>{const element=body.current;if(!element)return;const observer=new ResizeObserver(()=>setTruncated(element.scrollHeight>element.clientHeight+1));observer.observe(element);return()=>observer.disconnect();},[point.text,point.label,expanded]);
 return <li><span ref={body} className={expanded?'rp-point-text':'rp-point-text rp-clamp'}>{point.label&&<strong>{point.label}. </strong>}{point.text}</span>
 {!expandAll&&(truncated||open)&&<button type="button" className="rp-point rp-more" aria-expanded={open} onClick={()=>setOpen(o=>!o)}>{open?'Show less':'More'}</button>}</li>}
function Points({points,className}:{points:NotePoint[];className?:string}){const [all,setAll]=useState(false);return <><button type="button" className="rp-point rp-expand-all" aria-expanded={all} onClick={()=>setAll(a=>!a)}>{all?'Collapse all':'Expand all'}</button><ul className={'rp-points '+(className||'')}>{points.map((x,i)=><ClampPoint key={`${i}-${all}`} point={x} expandAll={all}/>)}</ul></>}

function Call({p}:{p:AnalysisPayload}){const note=parseNote(p.summary);const year=(p.horizons??[]).find(h=>h.label==='year'&&h.low?.value!=null&&h.high?.value!=null);
 return <>{note.headline&&<p className="rp-headline">{note.headline}</p>}
 {note.points.length>0&&<><h3>What is moving it</h3><Points points={note.points}/></>}
 {(year||note.outlook.year)&&<><h3>Next year</h3>
  {year?.middle?.value!=null&&<p className="rp-year">Average Wall Street target {money(year.middle.value)} <small>(range {money(year.low!.value)} – {money(year.high!.value)})</small></p>}
  {note.outlook.year?<p className="rp-text">{note.outlook.year}</p>:year?.note?<p className="rp-text">{year.note}</p>:null}</>}</>}

/** One row per level: name, price, how far it is from the current price, and why it is there. */
function TradePlan({p,price}:{p:AnalysisPayload;price:number|null}){
 const low=level(p,'buy_zone_low'),high=level(p,'buy_zone_high'),stop=level(p,'sl');
 const targets=['tp1','tp2','tp3'].map(n=>level(p,n)).filter((l):l is NonNullable<typeof l>=>l!=null&&l.price.value!=null);
 const keys=p.levels.filter(l=>l.label==='support'||l.label==='resistance');
 const short=p.direction==='bearish';
 const lo=low?.price.value??null,hi=high?.price.value??null,mid=lo!=null&&hi!=null?(lo+hi)/2:null;
 const ratio=mid!=null&&stop?.price.value!=null&&targets[0]?.price.value!=null&&mid!==stop.price.value?Math.abs(targets[0].price.value!-mid)/Math.abs(mid-stop.price.value):null;
 type Row={label:string;value:string;ref:number|null;tone?:string;why?:string|null};
 const upper=(s:string|null|undefined)=>s?s[0].toUpperCase()+s.slice(1)+(/[.!?]$/.test(s)?'':'.'):null;
 const rows:Row[]=targets.length===0?keys.map(k=>({label:k.label==='support'?'Support':'Resistance',value:money(k.price.value),ref:k.price.value,why:upper(k.note)})):[
  {label:short?'Short zone':'Buy zone',value:lo!=null&&hi!=null&&lo!==hi?money(lo)+' – '+money(hi):money(lo??hi),ref:mid??lo??hi,why:low?.note},
  {label:'Stop',value:money(stop?.price.value),ref:stop?.price.value??null,tone:'down',why:stop?.note},
  ...targets.map((t,i)=>({label:'Target '+(i+1),value:money(t.price.value),ref:t.price.value,tone:'up',why:upper(t.note)}))];
 if(rows.length===0)return null;
 return <><ul className="rp-rows">{rows.map(r=><li key={r.label}><div className="rp-row"><span className="rp-label">{r.label}</span><span className={'rp-val '+(r.tone||'')}>{r.value}</span>
  {price&&r.ref!=null&&<span className="rp-dist">{signedPct((r.ref/price-1)*100,1)}</span>}</div>{r.why&&<p className="rp-why">{r.why}</p>}</li>)}</ul>
 {ratio!=null&&<p className="rp-read">If it works, target 1 gains about ${ratio.toFixed(2)} for every $1 risked at the stop.</p>}</>}

const optionsHeadline=/\b\d+(?:\.\d+)?\s+(?:call|put)\b|\b[A-Z]{1,6}\d{6}[CP]\d{8}\b|\b(?:call|put)s?\s+options?\b|\boptions?\s+(?:activity|trading|trades?|volume|flow|chain|contracts?|expiration|expiry|strategy|strategies|market|prices?|moves?)\b|\bunusual\s+options?\b|\b(?:calls?|puts?)\s+(?:trading|trades?|volume|contracts?|expiration|expiry)\b/i;
const feedRows=(evidence:Evidence[])=>evidence.filter(e=>e.id.startsWith('news-')&&e.observed_at!=null&&e.observed_at>=Date.now()/1000-30*86400&&e.observed_at<=Date.now()/1000+3600&&!optionsHeadline.test(e.excerpt.split('\n')[0])).sort((a,b)=>(b.observed_at??0)-(a.observed_at??0)).slice(0,6);
function News({evidence}:{evidence:Evidence[]}){return <ul className="links">{feedRows(evidence).map(n=>{const [first,summary]=n.excerpt.split('\n');const m=/^(.*) \(([^()]+)\)$/.exec(first);
  const body=<><span>{m?m[1]:first}</span>{summary&&<span className="news-summary">{summary}</span>}<small>{m?m[2]+', ':''}{timeAgo(n.observed_at)}</small></>;
  return <li key={n.id}>{n.url?.startsWith('https://')?<a className="row-link" href={n.url} target="_blank" rel="noreferrer noopener" aria-label={(m?m[1]:first)+' (opens the article)'}>{body}<span className="chevron" aria-hidden="true">↗</span></a>:<div>{body}</div>}</li>;})}</ul>}
function AnalystCalls({evidence}:{evidence:Evidence[]}){return <ul className="links">{evidence.filter(e=>e.id.startsWith('analyst-')).slice(0,4).map(c=><li key={c.id}><p>{c.excerpt.replace(/^Analyst call:\s*/,'')}</p><small>{c.url?<SafeLink url={c.url}>{sourceLabel(c.url)}</SafeLink>:'Analyst'}{c.observed_at?', '+timeAgo(c.observed_at):''}</small></li>)}</ul>}

export type AnalysisPart='call'|'plan'|'risks'|'news'|'calls';
const partTitles:Record<AnalysisPart,string>={call:'The call',plan:'Trade plan',risks:'Risks',news:'Latest news',calls:'Analyst calls'};
/** One piece of the analysis as its own group, so the report page can place each where it belongs. */
export function AnalysisPart({result,part,price}:{result:SectionResult;part:AnalysisPart;price:number|null}){const p=result.payload;
 if(part==='call')return <ReportGroup result={result} title={partTitles.call} className="rp-call">{x=>x.kind==='analysis'?<Call p={x}/>:null}</ReportGroup>;
 if(p?.kind!=='analysis')return null;
 const note=parseNote(p.summary);
 if(part==='plan'){const rows=<TradePlan p={p} price={price}/>;return rows?<Group title={partTitles.plan} className="rp-plan-group">{rows}</Group>:null;}
 if(part==='risks')return note.risks.length>0?<Group title={partTitles.risks} className="rp-risks"><Points points={note.risks} className="rp-risk-points"/></Group>:null;
 if(part==='news')return feedRows(result.evidence).length>0?<Group title={partTitles.news} className="rp-news"><News evidence={result.evidence}/></Group>:null;
 return result.evidence.some(e=>e.id.startsWith('analyst-'))?<Group title={partTitles.calls} className="rp-calls"><AnalystCalls evidence={result.evidence}/></Group>:null}

/** Two columns of label and number (Yahoo/Apple style). Fields Schwab did not give are left out. */
export function KeyStats({quote}:{quote:Quote|null|undefined}){if(!quote)return null;
 const q=quote,rows:[string,string|null][]=[['Open',q.open!=null?money(q.open):null],['High',q.high!=null?money(q.high):null],['Low',q.low!=null?money(q.low):null],['Prev close',q.previous_close!=null?money(q.previous_close):null],
  ['Volume',q.volume!=null?compact(q.volume):null],['Avg volume',q.avg_volume!=null?compact(q.avg_volume):null],['52W high',q.high_52w!=null?money(q.high_52w):null],['52W low',q.low_52w!=null?money(q.low_52w):null],
  ['P/E',q.pe!=null?q.pe.toFixed(1):null],['Mkt cap',q.market_cap!=null?'$'+compact(q.market_cap):null],['Next earnings',q.next_earnings?formatDay(q.next_earnings)||null:null]];
 const shown=rows.filter((r):r is [string,string]=>r[1]!=null);
 return shown.length>0?<Group title="Key stats" className="rp-stats"><dl className="rp-stat-grid">{shown.map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></Group>:null}

const strike=(v:number|null)=>v==null?'':'$'+v.toLocaleString('en-US',{maximumFractionDigits:2});
export function Options({p}:{p:OptionsPayload}){const top=[...p.contracts].sort((a,b)=>(b.premium?.value??0)-(a.premium?.value??0)).slice(0,5);
 const ratio=p.put_call_ratio?.value;
 const read=ratio==null?null:ratio<0.7?'More calls than puts: traders lean bullish.':ratio>1?'More puts than calls: traders lean bearish.':'Calls and puts are roughly balanced.';
 return <><dl className="rp-three"><div><dt>Call volume</dt><dd>{compact(p.call_volume?.value)}</dd></div><div><dt>Put volume</dt><dd>{compact(p.put_volume?.value)}</dd></div><div><dt>Put/call</dt><dd>{ratio!=null?ratio.toFixed(2):'—'}</dd></div></dl>
 {read&&<p className="rp-read">{read}</p>}
 {top.length>0&&<><h3>Largest trades</h3><ul className="rp-rows">{top.map((c,i)=><li key={i}><div className="rp-row"><span className="rp-contract"><span className={c.side==='call'?'up':'down'}>{c.side==='call'?'Call':'Put'}</span> {strike(c.strike.value)} · {formatDay(c.expiry)}</span><span className="rp-val">{c.premium?.value!=null?'$'+compact(c.premium.value):'—'}</span></div>
  <p className="rp-why">Volume {compact(c.volume?.value)} · Open interest {compact(c.open_interest?.value)}</p></li>)}</ul></>}</>}

/** "Insiders sold $314.5M on the open market in 90 days", worked out from the Form 4 rows. */
function insiderLine(p:SecPayload){const by=new Map(p.insiders.map(i=>[i.accession,i]));const buyers=new Set<string>(),sellers=new Set<string>();let sold=0,bought=0;
 const filings=new Map(p.filings.map(f=>[f.accession,f]));
 for(const v of by.values()){if(v.conviction!=='conviction')continue;const f=filings.get(v.accession);
  const name=(v.reporter_name||f?.summary.split(' (')[0]||v.accession).trim().toLowerCase();
  const old=v.transaction_value?.value??0;
  const summary=f?.summary??'';
  const buy=v.bought_value?.value??(/\bbought\b/.test(summary)&&!/\bsold\b/.test(summary)?old:0);
  const sell=v.sold_value?.value??(/\bsold\b/.test(summary)&&!/\bbought\b/.test(summary)?old:0);
  if(buy>0){buyers.add(name);bought+=buy;}if(sell>0){sellers.add(name);sold+=sell;}}
 const part=(people:Set<string>,verb:string,amount:number)=>`${people.size} insider${people.size===1?'':'s'} ${verb} $${compact(amount)}`;
 const parts=[bought>0&&part(buyers,'bought',bought),sold>0&&part(sellers,'sold',sold)].filter(Boolean);
 const line=parts.length?parts.join('; ')+' in the last 90 days.':'No open-market insider trades in the last 90 days.';
 return p.coverage==='partial'?'Available filings: '+line+' Some filings could not be checked.':line;}
function tradeSummary(text:string){return text.split(/(\$[\d,.]+[KMBT]?|[\d,]+(?:\.\d+)?(?= shares\b))/g).map((part,i)=>/^(?:\$[\d,.]+[KMBT]?|[\d,]+(?:\.\d+)?)$/.test(part)?<strong key={i}>{part}</strong>:part);}
const formNames:Record<string,string>={'144':'Planned sale'};
export function Sec({p,message}:{p:SecPayload;message:string|null}){const [all,setAll]=useState(false);
 if(p.filings.length===0)return <p className="quiet">{message||'No filings in the last 90 days.'}</p>;
 const sorted=p.filings.filter(f=>!/: routine\b/i.test(f.summary)).sort((a,b)=>(b.filed_at??0)-(a.filed_at??0)),hidden=Math.max(0,sorted.length-8);
 const rows=all?sorted:sorted.slice(0,8);
 const side=(f:SecPayload['filings'][number])=>f.form==='4'&&f.detail_status==='ok'?
  /\) bought\b/.test(f.summary)?'buy':/\) sold\b/.test(f.summary)?'sell':null:null;
 return <><p className="rp-insider-line">{insiderLine(p)}</p>
 <ul className="filings">{rows.map(f=>{const direction=side(f);return <li key={f.accession}><span><SafeLink url={f.url}>{formNames[f.form]||f.title}</SafeLink>{direction&&<span className={'filing-side '+direction}>{direction==='buy'?'Buy':'Sell'}</span>}</span>{f.summary&&<p>{tradeSummary(f.summary)}</p>}<small>{formatShort(f.filed_at).split(',')[0]}</small></li>})}</ul>
 {hidden>0&&<button type="button" className="show-more" aria-expanded={all} onClick={()=>setAll(a=>!a)}>{all?'Show fewer':`Show all ${sorted.length}`}</button>}</>}

/** History's saved reports: the sections still show as panels, with the analysis split into the same groups. */
export function ResearchSection({result}:{result:SectionResult}){const p=result.payload;const busy=['queued','running'].includes(result.status);
 const price=p?.kind==='analysis'?p.quote?.price??null:null;
 return <section className="panel report-section" id={result.section}><header className="panel-head"><div><h2>{titles[result.section]}</h2></div>{busy&&<span className="pill pill-muted">Loading…</span>}</header>
 {busy&&!p&&<div className="skeleton-list"><span/><span/></div>}
 {!busy&&!p&&<p className="quiet">{result.section==='sec'&&result.message?result.message:unavailable[result.section]}</p>}
 {p?.kind==='analysis'&&(['call','plan','risks','news','calls'] as const).map(part=><AnalysisPart key={part} result={result} part={part} price={price}/>)}{p?.kind==='options'&&<Options p={p}/>}{p?.kind==='sec'&&<Sec p={p} message={result.message}/>}{p?.kind==='move'&&<ExpectedMove payload={p}/>}
 {p&&result.computed_at&&<p className="updated">Updated {formatShort(result.computed_at)}</p>}</section>}
