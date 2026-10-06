'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useSession} from './session';
import {AppShell} from './app-shell';
import {ResearchSection} from './research-section';
import {Chat} from './chat';
import {Direction} from './feed-card';
import {money} from '@/lib/format';
import {Button} from './ui/button';
import {useResearch} from '@/lib/use-research';
import {api,ApiError,primeResearch} from '@/lib/api';
import {sections,type ResearchRequest} from '@/lib/contracts';
export function TickerReport({symbol,requestId}:{symbol:string;requestId:string|null}){const {member}=useSession();const accessKey=JSON.stringify(member?.features);const {data,error}=useResearch(requestId,accessKey);const [refreshError,setRefreshError]=useState(''),[busy,setBusy]=useState(false),[asking,setAsking]=useState(false),[chatId,setChatId]=useState<string|null>(null);const alert=useRef<HTMLParagraphElement>(null);const router=useRouter();
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
 const shown=(s:typeof sections[number])=>member?.features[s].enabled;
 const section=(s:typeof sections[number])=>shown(s)&&data?.sections[s]?<ResearchSection key={s} result={data.sections[s]!}/>:null;
 const move=data?.sections.em_daily?.payload??data?.sections.em_weekly?.payload;
 const spot=move?.kind==='move'?move.spot?.value:null;
 const analysis=data?.sections.analysis?.payload;
 const canAsk=!!member?.features.assistant.enabled;
 return <AppShell><main className="workspace" id="main"><div className="page-head report-head"><div><h1 tabIndex={-1}>{ticker}</h1>{(spot!=null||analysis?.kind==='analysis')&&<p className="price">{spot!=null&&<span>{money(spot)}</span>}{analysis?.kind==='analysis'&&<Direction value={analysis.direction}/>}</p>}</div>
 <div className="report-actions">{canAsk&&<Button aria-expanded={asking} aria-controls="ask-sheet" onClick={()=>setAsking(a=>!a)}>{asking?'Close':'Ask about '+ticker}</Button>}{requestId&&<Button variant="outline" onClick={()=>void refresh()} disabled={busy}>{busy?'Refreshing…':'Refresh'}</Button>}</div></div>
 {canAsk&&asking&&<section id="ask-sheet" className="ask-sheet" aria-label={'Ask about '+ticker}><Chat conversationId={chatId} onConversation={ref=>setChatId(ref.id)} ticker={ticker} autoFocus
   suggestions={[`Is ${ticker} a buy right now?`,`What’s driving ${ticker} this week?`,`What are the risks?`]}/>
  {chatId&&<div className="ask-sheet-foot"><span>Saved to your chats.</span><Link href={'/assistant?c='+chatId}>Open in Assistant</Link></div>}</section>}
 {error&&<p role="alert">{error}</p>}{refreshError&&<p ref={alert} tabIndex={-1} role="alert">{refreshError}</p>}
 {!requestId?<div className="panel panel-empty">Search a ticker above to start a report.</div>:!data&&!error?<div className="panel"><div className="skeleton-list"><span/><span/><span/></div></div>:
 <div className="report-grid">{section('analysis')}<div className="report-pair">{section('em_daily')}{section('em_weekly')}</div>{section('options')}{section('sec')}</div>}
 </main></AppShell>}
