'use client';
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useSession} from './session';
import {AppShell} from './app-shell';
import {ResearchSection} from './research-section';
import {Button} from './ui/button';
import {useResearch} from '@/lib/use-research';
import {api,ApiError,primeResearch} from '@/lib/api';
import {sections,labels,type ResearchRequest} from '@/lib/contracts';
export function TickerReport({symbol,requestId}:{symbol:string;requestId:string|null}){const {member}=useSession();const accessKey=JSON.stringify(member?.features);const {data,error}=useResearch(requestId,accessKey);const [refreshError,setRefreshError]=useState(''),[busy,setBusy]=useState(false);const alert=useRef<HTMLParagraphElement>(null);const router=useRouter();
 const refreshController=useRef<AbortController|null>(null);
 useEffect(()=>()=>{refreshController.current?.abort();refreshController.current=null;},[]);
 async function refresh(){
  if(busy)return;
  refreshController.current?.abort();
  const current=new AbortController();refreshController.current=current;
  const active=()=>refreshController.current===current&&!current.signal.aborted;
  setBusy(true);setRefreshError('');
  try{
   const next=await api<ResearchRequest>('/research',{method:'POST',signal:current.signal,body:JSON.stringify({ticker:data?.ticker||symbol,refresh:true})});
   if(!active())return;
   primeResearch(next);router.replace('/ticker/'+encodeURIComponent(next.ticker)+'?request='+encodeURIComponent(next.id));
  }catch(e){
   if(!active())return;
   setRefreshError(e instanceof ApiError?e.message:'Unable to refresh.');window.dispatchEvent(new Event('focus'));
   setTimeout(()=>{if(active())alert.current?.focus();},0);
  }finally{if(active())setBusy(false);}
 }
 const ticker=data?.ticker||symbol;
 return <AppShell><main className="workspace" id="main"><div className="page-intro report-intro"><div><p className="eyebrow">TICKER RESEARCH</p><h1 tabIndex={-1}>{ticker} research</h1><p className="lede">Independent sections. Shared context. Transparent sources.</p></div>{requestId&&<Button variant="outline" onClick={()=>void refresh()} disabled={busy}>{busy?'Requesting…':'Refresh research'}</Button>}</div>{error&&<p role="alert">{error}</p>}{refreshError&&<p ref={alert} tabIndex={-1} role="alert">{refreshError}</p>}{!requestId?<div className="card empty-state">Use Research ticker to start all enabled sections.</div>:<div className="report-layout"><div className="report-column">{sections.map(section=>member?.features[section].enabled?data?.sections[section]?<ResearchSection key={section} result={data.sections[section]}/>:data?<section key={section} className="card"><h2>{labels[section]}</h2><p>No permitted result is available.</p></section>:null:<section key={section} className="card"><p>{labels[section]} is disabled.</p></section>)}{!data&&!error&&<p role="status">Loading your research…</p>}</div><aside className="report-sidebar"><div className="card"><p className="eyebrow">IN THIS REPORT</p><nav aria-label="Report sections">{sections.filter(s=>member?.features[s].enabled&&data?.sections[s]).map(s=><a key={s} href={'#'+s}>{labels[s]}<span aria-hidden="true">↗</span></a>)}</nav></div><div className="card context-note"><h2>Read with context</h2><p>Observation time tells you when a source measured something. Computation time tells you when this section was prepared.</p><p>A valid cache does not make an old observation fresh.</p><p>Expected moves are estimates, separate from trade setup targets.</p><span className="tag">All times Pacific</span></div>{member?.features.assistant.enabled&&<div className="card"><h2>Market Assistant</h2><p className="muted">Not available yet. No conversation has been started.</p></div>}</aside></div>}</main></AppShell>}
