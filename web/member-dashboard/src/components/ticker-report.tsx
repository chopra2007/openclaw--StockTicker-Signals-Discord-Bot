'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useSession} from './session';
import {AppShell} from './app-shell';
import {AnalysisPart,type AnalysisPayload,Group,KeyStats,Options,ReportGroup,Sec} from './research-section';
import {ExpectedMoveGroup} from './expected-move';
import {PriceChart,type ChartLevel} from './price-chart';
import {Chat} from './chat';
import {Direction} from './feed-card';
import {TickerLink} from './ticker-link';
import {WatchButton} from './watch-button';
import {formatWhen} from '@/lib/time';
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
 const sec=(s:typeof sections[number])=>shown(s)?data?.sections[s]:undefined;
 const analysisResult=sec('analysis');
 const move=data?.sections.em_daily?.payload??data?.sections.em_weekly?.payload;
 const spot=move?.kind==='move'?move.spot?.value??null:null;
 const analysis=analysisResult?.payload?.kind==='analysis'?analysisResult.payload:null;
 const quote=analysis?.quote,price=quote?.price??spot;
 const company=analysis?.company;
 const updated=Math.max(0,...Object.values(data?.sections??{}).map(r=>r?.computed_at??0))||null;
 const canAsk=!!member?.features.assistant.enabled;
 const part=(p:AnalysisPart)=>analysisResult?<AnalysisPart result={analysisResult} part={p} price={price}/>:null;
 const emD=sec('em_daily'),emW=sec('em_weekly');
 const options=sec('options'),filings=sec('sec');
 return <AppShell><main className="workspace" id="main"><div className="page-head report-head"><div><div className="rp-title"><h1 tabIndex={-1}>{ticker}</h1>{analysis&&<Direction value={analysis.direction}/>}</div>{(company||updated)&&<p className="rp-sub">{company}{company&&updated?' · ':''}{updated?'Updated '+formatWhen(updated):''}</p>}</div>
 <div className="report-actions"><WatchButton ticker={ticker}/>{canAsk&&<Button variant={requestId?undefined:"outline"} aria-expanded={asking} aria-controls="ask-sheet" onClick={()=>setAsking(a=>!a)}>{asking?'Close':'Ask about '+ticker}</Button>}{requestId&&<Button variant="outline" onClick={()=>void refresh()} disabled={busy}>{busy?'Refreshing…':'Refresh'}</Button>}</div></div>
 {canAsk&&asking&&<section id="ask-sheet" className="ask-sheet" aria-label={'Ask about '+ticker}><Chat conversationId={chatId} onConversation={ref=>setChatId(ref.id)} ticker={ticker} autoFocus
   suggestions={[`Is ${ticker} a buy right now?`,`What’s driving ${ticker} this week?`,`What are the risks?`]}/>
  {chatId&&<div className="ask-sheet-foot"><span>Saved to your chats.</span><Link href={'/assistant?c='+chatId}>Open in Assistant</Link></div>}</section>}
 {error&&<p role="alert">{error}</p>}{refreshError&&<p ref={alert} tabIndex={-1} role="alert">{refreshError}</p>}
 {!requestId?<div className="panel start-report"><p>Price levels, news, outlook and options for {symbol}.</p><TickerLink ticker={symbol} className="button button-primary">Get {symbol} report</TickerLink></div>:!data&&!error?<div className="panel"><div className="skeleton-list"><span/><span/><span/></div></div>:
 <div className="rp-wrap"><div className="rp-main">
  <PriceChart ticker={ticker} quote={quote} chart={analysis?.chart} levels={chartLevels(analysis)} fallbackPrice={price??null}/>
  {part('call')}{part('plan')}{part('risks')}{part('news')}</div>
 <div className="rp-rail"><KeyStats quote={quote}/>
  {(emD||emW)&&<Group title="Expected move" className="rp-em" note="How far option prices say it can move by each date."><ExpectedMoveGroup daily={emD} weekly={emW}/></Group>}
  {options&&<ReportGroup result={options} title="Options activity" className="rp-options">{p=>p.kind==='options'?<Options p={p}/>:null}</ReportGroup>}
  {filings&&<ReportGroup result={filings} title="SEC filings" className="rp-sec">{p=>p.kind==='sec'?<Sec p={p} message={filings.message}/>:null}</ReportGroup>}
  {part('calls')}</div></div>}
 </main></AppShell>}
/** The trade plan as lines on the chart: buy zone band, stop, targets. */
function chartLevels(a:AnalysisPayload|null):ChartLevel[]{if(!a)return [];const v=(n:string)=>a.levels.find(l=>l.label===n)?.price.value??null;
 const lo=v('buy_zone_low'),hi=v('buy_zone_high'),stop=v('sl'),out:ChartLevel[]=[];
 if(lo!=null&&hi!=null)out.push({label:a.direction==='bearish'?'Short zone':'Buy zone',low:Math.min(lo,hi),high:Math.max(lo,hi),kind:'zone'});
 if(stop!=null)out.push({label:'Stop',low:stop,kind:'stop'});
 ['tp1','tp2','tp3'].forEach((n,i)=>{const t=v(n);if(t!=null)out.push({label:'Target '+(i+1),low:t,kind:'target'});});
 return out}
