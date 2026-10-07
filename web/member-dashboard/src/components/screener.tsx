'use client';
import {useEffect,useRef,useState,useMemo} from 'react';
import Link from 'next/link';
import {SourceCall} from './source-call';
import {AppShell} from './app-shell';
import {useSession} from './session';
import {WatchButton} from './watch-button';
import {PriceChart} from './price-chart';
import {SafeLink} from './research-details';
import {useHistoryRead} from './history-list';
import {useWatchlistSnapshot,useWatched} from '@/lib/use-market';
import {useScreener} from '@/lib/use-screener';
import {money,timeAgo} from '@/lib/format';
import {pctText,tone} from '@/lib/market-format';
import {formatPacific,formatShort} from '@/lib/time';
import type {ReportPage,SavedReport} from '@/lib/contracts';
import {candidates,columns,columnLabels,conditions,defaultScreen,directionLabels,emptyFilters,savedSchema,screenCandidates,sortCandidates,validateFilters,type Candidate,type Column,type Filters,type Preferences,type Screen} from '@/lib/screener';

function usePreferences(memberId:string){
 const key='market-edge:screener:v1:'+memberId;
 const [value,setValue]=useState<Preferences>({version:1,current:defaultScreen,saved:[]}),[ready,setReady]=useState(false),[error,setError]=useState('');
 useEffect(()=>{const timer=setTimeout(()=>{try{const raw=localStorage.getItem(key);if(raw){const parsed=savedSchema.safeParse(JSON.parse(raw));if(parsed.success&&!validateFilters(parsed.data.current.filters)&&parsed.data.saved.every(s=>!validateFilters(s.screen.filters)))setValue(parsed.data);else setError('Saved settings were invalid. Defaults restored.');}}catch{setError('Browser storage is unavailable. Settings will only last for this visit.');}setReady(true);},0);return()=>clearTimeout(timer);},[key]);
 useEffect(()=>{if(!ready)return;try{localStorage.setItem(key,JSON.stringify(value));}catch{queueMicrotask(()=>setError('Browser storage is unavailable. Changes have not been saved.'));}},[key,value,ready]);
 return {value,setValue,ready,error};
}
export function Screener(){const {member}=useSession();return <AppShell>{member&&<ScreenWorkspace key={member.id} memberId={member.id} feed={member.features.feed.enabled} setups={member.features.setups.enabled} version={member.features.feed.version+':'+member.features.setups.version}/>}</AppShell>}
function ScreenWorkspace({memberId,feed,setups,version}:{memberId:string;feed:boolean;setups:boolean;version:string}){
 const prefs=usePreferences(memberId);const screen=prefs.value.current;
 const allowed=screen.universe==='both'?setups&&feed:screen.universe==='setups'?setups:feed;
 // A keyed data component makes revoked features discard their snapshots immediately.
 if(!prefs.ready)return <main id="main" className="workspace"><h1 tabIndex={-1}>Screener</h1><p role="status">Loading your screen settings…</p></main>;
 return <ScreenSurface key={version+allowed} memberId={memberId} feed={feed} setups={setups} prefs={prefs} allowed={allowed}/>;
}
function ScreenSurface({memberId,feed,setups,prefs,allowed}:{memberId:string;feed:boolean;setups:boolean;prefs:ReturnType<typeof usePreferences>;allowed:boolean}){
 const screen=prefs.value.current;
 const update=(patch:Partial<Screen>)=>prefs.setValue(v=>({...v,current:{...v.current,...patch}}));
 const [draft,setDraft]=useState<Filters>(screen.filters),[error,setError]=useState(''),[message,setMessage]=useState(''),[name,setName]=useState(''),[savedName,setSavedName]=useState(''),[selected,setSelected]=useState<Candidate|null>(null),[columnOpen,setColumnOpen]=useState(false),[filterOpen,setFilterOpen]=useState(false);
 const source=useScreener(screen.universe,memberId+(allowed?':'+screen.universe:':denied'),allowed);
 const watch=useWatchlistSnapshot();
 const liveWatched=useWatched();
 const watched=useMemo(()=>liveWatched??(watch.data?new Set(watch.data.items.map(i=>i.symbol)):null),[liveWatched,watch.data]);
 const [now,setNow]=useState(()=>Date.now()/1000);
 useEffect(()=>{document.querySelector<HTMLElement>('.screen-head h1')?.focus();},[]);
 useEffect(()=>{const t=setInterval(()=>setNow(Date.now()/1000),30000);return()=>clearInterval(t);},[]);
 const rows=useMemo(()=>candidates(allowed?source.cards??[]:[],source.quotes,now),[allowed,source.cards,source.quotes,now]);
 const matches=screenCandidates(rows,screen.filters,watched),sorted=sortCandidates(matches.rows,screen.sort,screen.descending);
 const active=conditions(screen.filters);
 const inspected=selected?matches.rows.find(r=>r.card.id===selected.card.id)??null:null;
 useEffect(()=>{if(selected&&!inspected){const timer=setTimeout(()=>setSelected(null),0);return()=>clearTimeout(timer);}},[selected,inspected]);
 const field=(key:keyof Filters,value:string|boolean)=>setDraft(d=>({...d,[key]:value}));
 function apply(e:React.FormEvent){e.preventDefault();const problem=validateFilters(draft);setError(problem);if(problem)return;update({filters:{...draft}});setSavedName('');setMessage('Filters applied.');}
 function reset(){setDraft({...emptyFilters});update({filters:{...emptyFilters}});setError('');setSavedName('');setMessage('Filters reset.');}
 function remove(key:keyof Filters){const next={...screen.filters};if(key==='minPrice'){next.minPrice='';next.maxPrice='';}else if(key==='minChange'){next.minChange='';next.maxChange='';}else if(key==='direction')next.direction='all';else if(key==='watched')next.watched=false;else next[key]='';setDraft(next);update({filters:next});setSavedName('');setError('');}
 function save(){const clean=name.trim();if(!clean){setMessage('Enter a screen name first.');return;}if(prefs.value.saved.length>=20&&!prefs.value.saved.some(s=>s.name===clean)){setMessage('You can save up to 20 screens in this browser.');return;}prefs.setValue(v=>({...v,saved:[...v.saved.filter(s=>s.name!==clean),{name:clean,screen:v.current}]}));setSavedName(clean);setName('');setMessage('Screen saved in this browser.');}
 function load(value:string){setSavedName(value);const saved=prefs.value.saved.find(s=>s.name===value);if(saved){prefs.setValue(v=>({...v,current:saved.screen}));setDraft(saved.screen.filters);setError('');setMessage('Saved screen loaded.');}}
 function order(column:Column,delta:number){const next=[...screen.columns],i=next.indexOf(column),j=i+delta;if(j<0||j>=next.length)return;[next[i],next[j]]=[next[j],next[i]];update({columns:next});}
 const dirty=JSON.stringify(draft)!==JSON.stringify(screen.filters);
 const sort=(column:Screen['sort'])=>update({sort:column,descending:screen.sort===column?!screen.descending:false});
 const sortButton=(column:Screen['sort'],label:string)=><button type="button" aria-label={'Sort by '+label.toLowerCase()} onClick={()=>sort(column)}>{label}{screen.sort===column?<span aria-hidden="true"> {screen.descending?'↓':'↑'}</span>:null}</button>;
 const initial=allowed&&source.cards===null;
 return <main id="main" className="workspace screen-workspace" data-density={screen.density}>
  <div className="page-head screen-head"><div><h1 tabIndex={-1}>Screener</h1><p>Find candidates in recent signals. Inspect the evidence before acting.</p></div><Link href="/">Overview feeds →</Link></div>
  <section className="screen-controls" aria-label="Universe and filters">
   <div className="screen-toolbar"><label>Universe<select aria-label="Universe" value={screen.universe} onChange={e=>{update({universe:e.target.value as Screen['universe']});setSavedName('');}}><option value="setups" disabled={!setups}>Recent trade setups</option><option value="alerts" disabled={!feed}>Recent group alerts</option><option value="both" disabled={!feed||!setups}>Trade setups &amp; group alerts</option></select></label>
    <label>Saved screens<select aria-label="Saved screens" value={savedName} onChange={e=>load(e.target.value)}><option value="">Select a saved screen</option>{prefs.value.saved.map(s=><option key={s.name} value={s.name}>{s.name}</option>)}</select></label>
    <details className="screen-save"><summary>Save current screen</summary><div className="screen-toolbar"><label>Screen name<input aria-label="Screen name" maxLength={60} value={name} placeholder="e.g. Bullish under $100" onChange={e=>setName(e.target.value)}/></label><button type="button" className="button button-outline" disabled={dirty} onClick={save}>Save screen</button></div></details>
    {savedName&&<button type="button" className="button button-ghost" onClick={()=>{prefs.setValue(v=>({...v,saved:v.saved.filter(s=>s.name!==savedName)}));setSavedName('');setMessage('Saved screen removed from this browser.');}}>Remove saved screen</button>}
   </div>
   <p className="screen-note">Up to 30 newest symbols per source from the last 7 days. This is a signal shortlist, not the whole market. Quotes are cached; data availability varies.</p>
   <button type="button" className="button button-primary screen-filter-toggle" aria-expanded={filterOpen} aria-controls="screen-filter-form" onClick={()=>setFilterOpen(v=>!v)}>{filterOpen?'Hide filters':'Edit filters'} ({active.length} active)</button>
   <form id="screen-filter-form" data-expanded={filterOpen} onSubmit={apply} noValidate>
    <div className="screen-filters"><fieldset><legend>Symbols</legend><label>Include symbols<input maxLength={256} value={draft.symbols} onChange={e=>field('symbols',e.target.value)} placeholder="All, or AAPL, NVDA"/></label><label>Exclude symbols<input maxLength={256} value={draft.exclude} onChange={e=>field('exclude',e.target.value)} placeholder="Optional"/></label></fieldset>
     <fieldset><legend>Price ($)</legend><label>Minimum price ($)<input type="text" inputMode="decimal" maxLength={24} value={draft.minPrice} onChange={e=>field('minPrice',e.target.value)} placeholder="No minimum"/></label><label>Maximum price ($)<input type="text" inputMode="decimal" maxLength={24} value={draft.maxPrice} onChange={e=>field('maxPrice',e.target.value)} placeholder="No maximum"/></label></fieldset>
     <fieldset><legend>Day change (%)</legend><label>Minimum day change (%)<input type="text" inputMode="decimal" maxLength={24} value={draft.minChange} onChange={e=>field('minChange',e.target.value)} placeholder="e.g. −2"/></label><label>Maximum day change (%)<input type="text" inputMode="decimal" maxLength={24} value={draft.maxChange} onChange={e=>field('maxChange',e.target.value)} placeholder="No maximum"/></label></fieldset>
     <fieldset><legend>Source context</legend><label>Source direction<select value={draft.direction} onChange={e=>field('direction',e.target.value)}><option value="all">Any direction</option>{Object.entries(directionLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><label>Maximum source age (hours)<input type="text" inputMode="decimal" maxLength={24} value={draft.maxAge} onChange={e=>field('maxAge',e.target.value)} placeholder="Up to 168"/></label></fieldset></div>
    <div className="screen-toolbar"><label className="screen-check"><input type="checkbox" checked={draft.watched} onChange={e=>field('watched',e.target.checked)}/>Only symbols on my watchlist</label><span className="screen-note">All conditions use AND. Numeric bounds include endpoints.</span><button type="submit" className="button button-primary" disabled={!allowed}>Apply filters</button><button type="button" className="button button-outline" onClick={reset}>Reset filters</button></div>
    {dirty&&<p className="screen-note">Unapplied changes. Results use the conditions below until you apply.</p>}{error&&<p role="alert">{error}</p>}
   </form>
  </section>
  <section className="screen-results" aria-labelledby="results-title">
   <div className="screen-toolbar screen-results-head"><h2 id="results-title">Results</h2><p role="status">{!allowed?'This universe is disabled. Choose another above.':initial?source.failed?'Data unavailable. Retry refresh.':'Loading cached data…':`${sorted.length} of ${rows.length} symbols matched`}</p><button type="button" className="button button-outline" disabled={source.busy||!allowed} onClick={source.refresh}>{source.busy?'Refreshing…':'Refresh data'}</button><button type="button" className="button button-outline" aria-expanded={columnOpen} aria-controls="screen-columns" onClick={()=>setColumnOpen(v=>!v)}>Columns</button><label>Density<select value={screen.density} onChange={e=>update({density:e.target.value as Screen['density']})}><option value="compact">Compact</option><option value="comfortable">Comfortable</option></select></label></div>
   <div className="screen-context"><span>{screen.universe==='both'?'Trade setups & group alerts':screen.universe==='setups'?'Recent trade setups':'Recent group alerts'}</span><span>Source window: 7 days</span><span>Cached quote refresh: about 1 minute</span><span>{source.checked?'Checked '+formatPacific(source.checked):'Not checked yet'}</span></div>
   {source.failed&&!initial&&<p role="status" className="screen-warning">Refresh failed. Some cached data is retained; quotes may be stale.</p>}
   {prefs.error&&<p role="alert">{prefs.error}</p>}<p className="screen-note" role="status">{message}</p>
   <div className="screen-chips" aria-label="Active conditions">{active.length?active.map(c=><button type="button" key={c.key} aria-label={'Remove '+c.label+' condition'} onClick={()=>remove(c.key)}>{c.label}: {c.required} <span aria-hidden="true">×</span></button>):<span>No filters. All available symbols in this universe qualify.</span>}</div>
   {screen.filters.watched&&(!watched||watch.failed)&&<p role="status" className="screen-warning">{watch.failed?'Watchlist refresh failed.':'Loading watchlist…'} {watched?'Using the last watchlist snapshot.':'Matches cannot be determined yet.'}</p>}
   {matches.missing>0&&<p className="screen-note">{matches.missing} {matches.missing===1?'symbol lacks':'symbols lack'} data needed for these filters.</p>}
   {columnOpen&&<div id="screen-columns" className="screen-column-menu"><p className="screen-note">Symbol stays pinned. Move columns with the arrow buttons; preferences are saved locally.</p>{columns.map(c=><div key={c}><label className="screen-check"><input type="checkbox" aria-label={'Show '+columnLabels[c].toLowerCase()} checked={screen.columns.includes(c)} onChange={e=>update({columns:e.target.checked?[...screen.columns,c]:screen.columns.filter(v=>v!==c)})}/>{columnLabels[c]}</label><button type="button" disabled={!screen.columns.includes(c)||screen.columns.indexOf(c)===0} aria-label={'Move '+columnLabels[c].toLowerCase()+' left'} onClick={()=>order(c,-1)}>←</button><button type="button" disabled={!screen.columns.includes(c)||screen.columns.indexOf(c)===screen.columns.length-1} aria-label={'Move '+columnLabels[c].toLowerCase()+' right'} onClick={()=>order(c,1)}>→</button></div>)}</div>}
   {!initial&&allowed&&!(screen.filters.watched&&!watched)&&sorted.length===0?<div className="empty-state"><p>{rows.length?'No stocks meet these conditions.':'No symbols are available in this source right now.'}</p><p className="small">{rows.length?'Relax a condition or reset the filters.':'Try the other universe or refresh later.'}</p></div>:!initial&&allowed&&<div className="screen-table-wrap" role="region" aria-label="Screening results, scroll horizontally for more columns" tabIndex={0}><table className="screen-table"><caption className="sr-only">Cached signal candidates. Activate a symbol to inspect its match conditions.</caption><thead><tr><th scope="col" aria-sort={screen.sort==='symbol'?screen.descending?'descending':'ascending':'none'}>{sortButton('symbol','Symbol')}</th>{screen.columns.map(c=><th key={c} scope="col" className={'screen-col-'+c} aria-sort={screen.sort===c?screen.descending?'descending':'ascending':'none'}>{c==='reason'?columnLabels[c]:sortButton(c,c==='change'?'Day change':c==='age'?'Source age':c==='direction'?'Source direction':'Price')}</th>)}<th scope="col">Watch</th></tr></thead><tbody>{sorted.map(row=><tr key={row.card.ticker} data-selected={selected?.card.ticker===row.card.ticker||undefined}><th scope="row"><button type="button" className="screen-symbol" aria-label={'Inspect '+row.card.ticker} onClick={()=>setSelected(row)}>{row.card.ticker}</button></th>{screen.columns.map(c=><td key={c} className={'screen-col-'+c+(c==='change'?' '+tone(row.quote?.change_pct):'')}>{c==='price'?<div className='screen-price'>{money(row.quote?.price)}<small title={formatPacific(row.quote?.quote_time)}>{row.quote?.quote_time?formatShort(row.quote.quote_time):'Time unavailable'}</small></div>:c==='change'?pctText(row.quote?.change_pct):c==='direction'?directionLabels[row.card.direction]:c==='age'?timeAgo(row.card.observed_at,now):active.length?active.map(a=>a.label).join(' · '):'In selected universe'}</td>)}<td><WatchButton ticker={row.card.ticker}/></td></tr>)}</tbody></table></div>}
   <p className="screen-note screen-foot">Price is an observed cached quote. Day change is calculated from the previous close. Source direction describes the source, not a recommendation. No score or ranking predicts returns.</p>
  </section>
  {inspected&&<CandidateDrawer key={inspected.card.ticker} row={inspected} filters={screen.filters} universe={screen.universe} accessKey={memberId} onClose={()=>setSelected(null)}/>}
 </main>;
}
function CandidateDrawer({row,filters,accessKey,onClose}:{row:Candidate;filters:Filters;universe:Screen['universe'];accessKey:string;onClose:()=>void}){
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const el=dialog.current!,opener=document.activeElement as HTMLElement|null;el.showModal();return()=>{el.close();if(opener?.isConnected)opener.focus();else document.querySelector<HTMLElement>('.screen-head h1')?.focus();};},[]);
 const reportList=useHistoryRead<ReportPage>('/reports?limit=100',accessKey);
 const reportRef=reportList.data?.items.find(r=>r.ticker===row.card.ticker);
 const saved=useHistoryRead<SavedReport>(reportRef?'/reports/'+encodeURIComponent(reportRef.id):null,accessKey);
 const analysis=saved.data?.sections.analysis,content=analysis?.payload?.kind==='analysis'?analysis.payload:null;
 const active=conditions(filters),plan=row.card.plan,chart=content?.chart??row.card.chart,chartAt=content?.chart?analysis?.observed_at:row.card.chart_at;
 const observed=(key:keyof Filters)=>key==='minPrice'?money(row.quote?.price):key==='minChange'?pctText(row.quote?.change_pct):key==='maxAge'?row.age.toFixed(1)+' h':key==='direction'?directionLabels[row.card.direction]:key==='watched'?'On your watchlist':row.card.ticker;
 return <dialog ref={dialog} className="candidate-drawer" aria-labelledby="candidate-title" onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget){const box=e.currentTarget.getBoundingClientRect();if(e.clientX<box.left||e.clientX>box.right||e.clientY<box.top||e.clientY>box.bottom)onClose();}}}>
  <div className="candidate-head"><div><h2 id="candidate-title">{row.card.ticker}</h2>{(content?.company||row.card.company)&&<p>{content?.company||row.card.company}</p>}</div><button type="button" className="button button-outline" autoFocus onClick={onClose}>Close inspection</button></div>
  <div className="candidate-body"><section><p className="candidate-price">{money(row.quote?.price)} <span className={tone(row.quote?.change_pct)}>{pctText(row.quote?.change_pct)}</span></p><p className="screen-note">{row.quote?.quote_time?'Quote '+formatPacific(row.quote.quote_time):'Quote timestamp unavailable.'} · Inspection snapshot</p></section>
   <section><h3>Why it matched</h3><p>{row.card.plan?'In recent trade setups: a recent bot alert has a calculated entry/stop and at least one target':'In recent group alerts: multiple analysts posted this symbol'}. All active conditions passed.</p>{active.length?<dl className="match-reasons">{active.map(c=><div key={c.key}><dt>{c.label}</dt><dd><strong>{observed(c.key)}</strong><span>Required: {c.required}</span></dd></div>)}</dl>:<p className="screen-note">No filters are active. Inclusion in this source is the only condition.</p>}</section>
   <section><h3>Price chart</h3>{chart?<><p className="screen-note">{content?.chart?'Saved report data':'Cached setup daily closes'}, {formatPacific(chartAt)}{analysis?.stale?' · Stale':''}. Separate from the cached screening quote. Range buttons show available samples up to the selected period; gaps and short histories may limit coverage.</p><PriceChart ticker={row.card.ticker} quote={content?.quote} chart={chart} levels={[]} fallbackPrice={null}/><details><summary>Chart data (daily closes)</summary><div className="chart-data"><table><thead><tr><th>Date (Pacific)</th><th>Close ($)</th></tr></thead><tbody>{chart.daily.map(([t,v])=><tr key={t}><td>{formatPacific(t)}</td><td>{money(v)}</td></tr>)}</tbody></table></div></details></>:<p className="screen-note">{reportList.error||saved.error?'Saved research is unavailable.':reportList.data===null||reportRef&&!saved.data?'Checking saved research…':reportRef?'Your latest saved report for this symbol has no chart. Check History for other saved research.':'No report for this symbol among your latest 100 saved reports. Inspection does not start new research.'}</p>}</section>
   <section><h3>Source evidence</h3><p className="screen-note">Observed {formatPacific(row.card.observed_at)} · {directionLabels[row.card.direction]}</p><p className="screen-note">Source: {row.card.source?.replaceAll('_',' ')||'Recent signal'}. Source direction and calculated trade direction are separate.</p><p className="candidate-evidence">{row.card.text||'No detailed catalyst was recorded for this alert.'}</p>{row.card.url&&<SafeLink url={row.card.url}>Open original source ↗</SafeLink>}{row.card.group&&<ul className="candidate-calls">{row.card.group.calls.map((c,i)=><li key={i}><SourceCall call={c}/></li>)}</ul>}</section>
   {plan&&<section><h3>Calculated trade levels</h3><p className="screen-note">{plan.direction} · Calculated {formatPacific(plan.computed_at)}. Calculated from market inputs, not AI-generated buy/sell instructions. Inspect liquidity and risk separately.</p><dl className="match-reasons"><div><dt>Entry range</dt><dd>{money(plan.entry_low)}–{money(plan.entry_high)}</dd></div><div><dt>Stop</dt><dd>{money(plan.stop)}</dd></div>{plan.targets.map((v,i)=><div key={i}><dt>Target {i+1}</dt><dd>{money(v)}</dd></div>)}</dl></section>}
   <p className="screen-note">Volume, volatility and liquidity measures are not in this cached screen. Missing data is not evidence of low risk.</p>
   <div className="screen-toolbar"><WatchButton ticker={row.card.ticker}/><Link href="/history">Saved research →</Link><Link href={'/ticker/'+encodeURIComponent(row.card.ticker)}>Open report page →</Link></div><p className="screen-note">The report page offers existing research actions, which may use the site’s AI budget. Opening this inspection never submits those actions.</p>
  </div>
 </dialog>;
}
