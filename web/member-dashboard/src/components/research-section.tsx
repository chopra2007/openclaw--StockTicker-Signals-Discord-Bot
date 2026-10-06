import {labels,type SectionResult} from '@/lib/contracts';
import {formatShort,formatDay} from '@/lib/time';
import {compact,money,summarize} from '@/lib/format';
import {EvidenceList,SafeLink} from './research-details';
import {ExpectedMove} from './expected-move';
import {Direction} from './feed-card';
type Payload=NonNullable<SectionResult['payload']>;
const level=(p:Extract<Payload,{kind:'analysis'}>,name:string)=>p.levels.find(l=>l.label===name)?.price.value??null;
function Analysis({p}:{p:Extract<Payload,{kind:'analysis'}>}){const {headline,points}=summarize(p.summary);
 const low=level(p,'buy_zone_low'),high=level(p,'buy_zone_high'),stop=level(p,'sl');const targets=['tp1','tp2','tp3'].map(n=>level(p,n)).filter((v):v is number=>v!=null);
 const entry=low!=null&&high!=null&&low!==high?money(low)+' – '+money(high):money(low??high);
 return <><div className="summary-head"><Direction value={p.direction}/></div>
 {headline&&<p className="summary-headline">{headline}</p>}{points.length>0&&<ul className="summary-points">{points.map((s,i)=><li key={i}>{s}</li>)}</ul>}
 {(stop!=null||targets.length>0)&&<div className="trade-plan"><h3>Trade plan</h3><dl className="plan"><div><dt>Entry</dt><dd>{entry}</dd></div><div><dt>Stop</dt><dd className="down">{money(stop)}</dd></div><div><dt>Targets</dt><dd className="up">{targets.map(money).join(' · ')||'—'}</dd></div></dl></div>}
 {p.catalysts.length>0&&<><h3>Catalysts</h3><ul className="summary-points">{p.catalysts.slice(0,4).map((c,i)=><li key={i}>{c}</li>)}</ul></>}
 {p.conflicts.length>0&&<><h3>Watch out for</h3><ul className="summary-points">{p.conflicts.slice(0,3).map((c,i)=><li key={i}>{c}</li>)}</ul></>}</>}
function Options({p}:{p:Extract<Payload,{kind:'options'}>}){const top=[...p.contracts].sort((a,b)=>(b.premium?.value??0)-(a.premium?.value??0)).slice(0,5);
 const stats=[['Calls',compact(p.call_volume?.value)],['Puts',compact(p.put_volume?.value)],['Put/Call',p.put_call_ratio?.value!=null?p.put_call_ratio.value.toFixed(2):'—'],['Call $',p.call_premium?.value!=null?'$'+compact(p.call_premium.value):null],['Put $',p.put_premium?.value!=null?'$'+compact(p.put_premium.value):null]].filter(([,v])=>v!=null);
 return <><dl className="stats">{stats.map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
 {top.length>0&&<><h3>Largest trades</h3><table className="table"><thead><tr><th>Contract</th><th>Volume</th><th>Open int.</th><th>Premium</th></tr></thead><tbody>{top.map((c,i)=><tr key={i}><td><span className={c.side==='call'?'up':'down'}>{c.side==='call'?'Call':'Put'}</span> {money(c.strike.value)} · {formatDay(c.expiry)}</td><td>{compact(c.volume?.value)}</td><td>{compact(c.open_interest?.value)}</td><td>{c.premium?.value!=null?'$'+compact(c.premium.value):'—'}</td></tr>)}</tbody></table>
 {p.contracts.length>5&&<p className="quiet">Showing the 5 largest of {p.contracts.length} unusual trades.</p>}</>}</>}
function Sec({p,message}:{p:Extract<Payload,{kind:'sec'}>;message:string|null}){
 return <>{p.filings.length===0&&p.insiders.length===0&&<p className="quiet">{message||'No new filings in the last 3 days.'}</p>}
 {p.filings.length>0&&<ul className="filings">{p.filings.slice(0,8).map(f=><li key={f.accession}><span className="pill pill-muted">{f.form}</span><div><SafeLink url={f.url}>{f.title}</SafeLink><p>{f.summary}</p></div><small>{formatShort(f.filed_at)}</small></li>)}</ul>}
 {p.insiders.length>0&&<><h3>Insider trades</h3><ul className="summary-points">{p.insiders.slice(0,5).map(i=><li key={i.accession}>{i.summary}</li>)}</ul></>}</>}
const unavailable:Record<string,string>={em_daily:'Not available right now (option quotes are too thin, often outside market hours).',em_weekly:'Not available right now (option quotes are too thin, often outside market hours).',options:'No option data right now.',analysis:'Analysis isn’t available right now. Try Refresh in a minute.',sec:'SEC filings aren’t available right now.'};
export function ResearchSection({result}:{result:SectionResult}){const p=result.payload;const busy=['queued','running'].includes(result.status);
 return <section className="panel report-section" id={result.section}><header className="panel-head"><h2>{labels[result.section]}</h2>{busy&&<span className="pill pill-muted">Loading…</span>}</header>
 {busy&&!p&&<div className="skeleton-list"><span/><span/></div>}
 {!busy&&!p&&<p className="quiet">{result.section==='sec'&&result.message?result.message:unavailable[result.section]}</p>}
 {p?.kind==='analysis'&&<Analysis p={p}/>}{p?.kind==='options'&&<Options p={p}/>}{p?.kind==='sec'&&<Sec p={p} message={result.message}/>}{p?.kind==='move'&&<ExpectedMove payload={p}/>}
 {p&&p.kind!=='move'&&<EvidenceList items={result.evidence}/>}
 {p&&result.computed_at&&<p className="updated">Updated {formatShort(result.computed_at)}</p>}</section>}
