import type {Evidence,SectionResult} from '@/lib/contracts';
import {formatShort,formatDay} from '@/lib/time';
import {compact,money,parseNote,sourceLabel,timeAgo,type NotePoint} from '@/lib/format';
import {SafeLink} from './research-details';
import {ExpectedMove} from './expected-move';
type Payload=NonNullable<SectionResult['payload']>;
const titles:Record<SectionResult['section'],string>={analysis:'Analysis',em_daily:'Expected move today',em_weekly:'Expected move this week',options:'Options activity',sec:'SEC filings'};
type AnalysisPayload=Extract<Payload,{kind:'analysis'}>;
const level=(p:AnalysisPayload,name:string)=>p.levels.find(l=>l.label===name);
const Point=({point}:{point:NotePoint})=><li>{point.label&&<strong>{point.label}. </strong>}{point.text}</li>;
const horizonNames={week:'Next week',month:'Next month',year:'Next year'} as const;

/** Owner 2026-10-06 (Gemini comparison): catalysts, a week / month / year outlook, and why each level is there. */
function Analysis({p,evidence}:{p:AnalysisPayload;evidence:Evidence[]}){const note=parseNote(p.summary);
 const low=level(p,'buy_zone_low'),high=level(p,'buy_zone_high'),stop=level(p,'sl');
 const targets=['tp1','tp2','tp3'].map(n=>level(p,n)).filter((l):l is NonNullable<typeof l>=>l!=null&&l.price.value!=null);
 const entry=low?.price.value!=null&&high?.price.value!=null&&low.price.value!==high.price.value?money(low.price.value)+' – '+money(high.price.value):money(low?.price.value??high?.price.value);
 const short=p.direction==='bearish';
 const mid=low?.price.value!=null&&high?.price.value!=null?(low.price.value+high.price.value)/2:null;
 const ratio=mid!=null&&stop?.price.value!=null&&targets[0]?.price.value!=null&&mid!==stop.price.value?Math.abs(targets[0].price.value!-mid)/Math.abs(mid-stop.price.value):null;
 const keys=p.levels.filter(l=>l.label==='support'||l.label==='resistance');
 const horizons=(p.horizons??[]).filter(h=>h.low?.value!=null&&h.high?.value!=null);
 const outlook=(['week','month','year'] as const).filter(k=>note.outlook[k]||horizons.some(h=>h.label===k));
 const news=evidence.filter(e=>e.id.startsWith('news-')).sort((a,b)=>(b.observed_at??0)-(a.observed_at??0)).slice(0,6);
 const calls=evidence.filter(e=>e.id.startsWith('analyst-')).slice(0,4);
 return <>{note.headline&&<p className="summary-headline">{note.headline}</p>}
 {note.points.length>0&&<><h3>Catalysts</h3><ul className="summary-points">{note.points.map((x,i)=><Point key={i} point={x}/>)}</ul></>}
 {outlook.length>0&&<><h3>Outlook</h3><dl className="outlook">{outlook.map(k=>{const h=horizons.find(x=>x.label===k);
  return <div key={k}><dt>{horizonNames[k]}</dt><dd>{h&&<span className="range">{k==='year'&&h.middle?.value!=null?<>Average target {money(h.middle.value)} <small>(range {money(h.low!.value)} – {money(h.high!.value)})</small></>:<>{money(h.low!.value)} – {money(h.high!.value)}</>}</span>}
   {note.outlook[k]?<p>{note.outlook[k]}</p>:h?.note?<p>{h.note}</p>:null}</dd></div>;})}</dl></>}
 {targets.length>0&&<div className="trade-plan"><h3>Trade plan</h3><dl className="plan">
  <div><dt>{short?'Short zone':'Buy zone'}</dt><dd>{entry}{low?.note&&<small>{low.note}</small>}</dd></div>
  <div><dt>Stop</dt><dd><span className="down">{money(stop?.price.value)}</span>{stop?.note&&<small>{stop.note}</small>}</dd></div>
  {targets.map((t,i)=><div key={t.label}><dt>Target {i+1}</dt><dd><span className="up">{money(t.price.value)}</span>{t.note&&<small>{t.note[0].toUpperCase()+t.note.slice(1)}.</small>}</dd></div>)}
 </dl>{ratio!=null&&<p className="read">Target 1 pays {ratio.toFixed(1)} times the risk to the stop.</p>}</div>}
 {targets.length===0&&keys.length>0&&<><h3>Key levels</h3><dl className="plan">{keys.map((k,i)=><div key={i}><dt>{k.label==='support'?'Support':'Resistance'}</dt><dd>{money(k.price.value)}{k.note&&<small>{k.note}</small>}</dd></div>)}</dl></>}
 {note.risks.length>0&&<><h3>Risks</h3><ul className="summary-points risks">{note.risks.map((x,i)=><Point key={i} point={x}/>)}</ul></>}
 {news.length>0&&<><h3>Latest news</h3><ul className="links">{news.map(n=>{const [first,summary]=n.excerpt.split('\n');const m=/^(.*) \(([^()]+)\)$/.exec(first);
  const body=<><span>{m?m[1]:first}</span>{summary&&<span className="news-summary">{summary}</span>}<small>{m?m[2]+', ':''}{timeAgo(n.observed_at)}</small></>;
  return <li key={n.id}>{n.url?.startsWith('https://')?<a className="row-link" href={n.url} target="_blank" rel="noreferrer noopener" aria-label={(m?m[1]:first)+' (opens the article)'}>{body}<span className="chevron" aria-hidden="true">↗</span></a>:<div>{body}</div>}</li>;})}</ul></>}
 {calls.length>0&&<><h3>Analyst calls</h3><ul className="links">{calls.map(c=><li key={c.id}><p>{c.excerpt.replace(/^Analyst call:\s*/,'')}</p><small>{c.url?<SafeLink url={c.url}>{sourceLabel(c.url)}</SafeLink>:'Analyst'}{c.observed_at?', '+timeAgo(c.observed_at):''}</small></li>)}</ul></>}</>}

function Options({p}:{p:Extract<Payload,{kind:'options'}>}){const top=[...p.contracts].sort((a,b)=>(b.premium?.value??0)-(a.premium?.value??0)).slice(0,5);
 const ratio=p.put_call_ratio?.value;
 const read=ratio==null?null:ratio<0.7?'More calls than puts: traders lean bullish.':ratio>1?'More puts than calls: traders lean bearish.':'Calls and puts are roughly balanced.';
 return <><dl className="stats"><div><dt>Call volume</dt><dd>{compact(p.call_volume?.value)}</dd></div><div><dt>Put volume</dt><dd>{compact(p.put_volume?.value)}</dd></div><div><dt>Put/call ratio</dt><dd>{ratio!=null?ratio.toFixed(2):'—'}</dd></div></dl>
 {read&&<p className="read">{read}</p>}
 {top.length>0&&<><h3>Largest trades</h3><table className="table"><thead><tr><th>Contract</th><th>Volume</th><th>Open interest</th><th>Paid</th></tr></thead><tbody>{top.map((c,i)=><tr key={i}><td><span className={c.side==='call'?'up':'down'}>{c.side==='call'?'Call':'Put'}</span> {money(c.strike.value)}, {formatDay(c.expiry)}</td><td>{compact(c.volume?.value)}</td><td>{compact(c.open_interest?.value)}</td><td>{c.premium?.value!=null?'$'+compact(c.premium.value):'—'}</td></tr>)}</tbody></table></>}</>}

function Sec({p,message}:{p:Extract<Payload,{kind:'sec'}>;message:string|null}){
 if(p.filings.length===0)return <p className="quiet">{message||'No filings in the last 90 days.'}</p>;
 return <ul className="filings">{p.filings.slice(0,10).map(f=><li key={f.accession}><span><SafeLink url={f.url}>{f.title}</SafeLink><span className="form-code">{f.form==='4'?'Form 4':f.form}</span></span>{f.summary&&<p>{f.summary}</p>}<small>{formatShort(f.filed_at).split(',')[0]}</small></li>)}</ul>}

const unavailable:Record<string,string>={em_daily:'Not available right now. Option prices are too thin, usually outside market hours.',em_weekly:'Not available right now. Option prices are too thin, usually outside market hours.',options:'No options data right now.',analysis:'Analysis isn’t available right now. Try Refresh in a minute.',sec:'SEC filings aren’t available right now.'};
const notes:Partial<Record<SectionResult['section'],string>>={em_daily:'How far options traders expect the price to move by the next close.',em_weekly:'How far options traders expect the price to move by the end of the week.'};
export function ResearchSection({result}:{result:SectionResult}){const p=result.payload;const busy=['queued','running'].includes(result.status);
 return <section className="panel report-section" id={result.section}><header className="panel-head"><div><h2>{titles[result.section]}</h2>{notes[result.section]&&<p>{notes[result.section]}</p>}</div>{busy&&<span className="pill pill-muted">Loading…</span>}</header>
 {busy&&!p&&<div className="skeleton-list"><span/><span/></div>}
 {!busy&&!p&&<p className="quiet">{result.section==='sec'&&result.message?result.message:unavailable[result.section]}</p>}
 {p?.kind==='analysis'&&<Analysis p={p} evidence={result.evidence}/>}{p?.kind==='options'&&<Options p={p}/>}{p?.kind==='sec'&&<Sec p={p} message={result.message}/>}{p?.kind==='move'&&<ExpectedMove payload={p}/>}
 {p&&result.computed_at&&<p className="updated">Updated {formatShort(result.computed_at)}</p>}</section>}
