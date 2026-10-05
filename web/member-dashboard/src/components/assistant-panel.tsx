'use client';
import Link from 'next/link';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from '@/lib/api';
import type {AssistantRun,ConversationPage,ConversationRef,SavedConversation} from '@/lib/contracts';
import {formatPacific} from '@/lib/time';
import {AppShell} from './app-shell';
import {useSession} from './session';
import {useHistoryRead} from './history-list';
import {EvidenceList} from './research-details';
import {Button} from './ui/button';

export function AssistantPanel({ticker}:{ticker:string|null}){
 const {member}=useSession();
 const [selected,setSelected]=useState<string|null>(null),[runId,setRunId]=useState<string|null>(null);
 const [title,setTitle]=useState('Market research'),[message,setMessage]=useState(''),[retryText,setRetryText]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0),[pending,setPending]=useState(false);
 const operation=useRef<AbortController|null>(null);
 const allowed=!!member?.features.assistant.enabled;
 const accessKey=member?.id+JSON.stringify(member?.features);
 useEffect(()=>()=>{operation.current?.abort();},[accessKey]);
 const list=useHistoryRead<ConversationPage>(allowed?'/conversations':null,accessKey+revision);
 const run=useHistoryRead<AssistantRun>(allowed&&selected?`/conversations/${selected}/runs/${runId||'latest'}`:null,accessKey+revision,1000);
 const active=run.data?.status==='queued'||run.data?.status==='running';
 const detail=useHistoryRead<SavedConversation>(allowed&&selected?'/conversations/'+selected:null,accessKey+revision+(run.data?.finished_at||''));
 const waiting=run.data?active:pending;
 const selectedTicker=ticker??run.data?.ticker_context??null;
 const retryQuestion=retryText||detail.data?.messages.filter(m=>m.role==='user').at(-1)?.text||'';
 async function mutate(kind:'create'|'send'|'retry'|'delete'){
  if(busy||!allowed)return;
  const controller=new AbortController();operation.current=controller;setBusy(true);setError('');
  const current=()=>operation.current===controller&&!controller.signal.aborted;
  try{
   if(kind==='create'){
    const next=await api<ConversationRef>('/conversations',{method:'POST',body:JSON.stringify({title}),signal:controller.signal});
    if(current()){setSelected(next.id);setRunId(null);setRetryText('');setPending(false);}
   }else if(kind==='delete'&&selected){
    const identity=selected;setSelected(null);setRunId(null);setPending(false);
    await api('/conversations/'+identity,{method:'DELETE',signal:controller.signal});
   }else if(selected){
    const text=kind==='retry'?retryQuestion:message;
    const next=await api<AssistantRun>('/conversations/'+selected+'/messages',{method:'POST',body:JSON.stringify({message:text,ticker_context:selectedTicker}),signal:controller.signal});
    if(current()){setRunId(next.id);setPending(next.status==='queued'||next.status==='running');setRetryText(text);setMessage('');}
   }
   if(current())setRevision(x=>x+1);
  }catch(e){if(current())setError(e instanceof ApiError?e.message:'Unable to submit this request.');}
  finally{if(current())setBusy(false);}
 }
 return <AppShell><main id="main" className="workspace"><div className="page-intro"><p className="eyebrow">PRIVATE CONVERSATIONS</p><h1>Market Assistant</h1><p className="lede">Ask about permitted market evidence. Answers are saved after current access is checked.</p><p>Selected ticker: <strong>{selectedTicker||'None'}</strong></p></div>{!allowed?<p role="status">Market Assistant is disabled.</p>:<div className="report-layout history-layout"><aside className="report-sidebar"><section className="card"><h2>Your conversations</h2><label htmlFor="conversation-title">Conversation title</label><input id="conversation-title" value={title} maxLength={256} onChange={e=>setTitle(e.target.value)}/><Button disabled={busy||!title.trim()} onClick={()=>void mutate('create')}>New conversation</Button>{list.error&&<p role="alert">{list.error}</p>}{list.data?.items.map(c=><Button variant="outline" key={c.id} onClick={()=>{operation.current?.abort();setBusy(false);setSelected(c.id);setRunId(null);setPending(false);setRetryText('');}}>{c.title}</Button>)}<p><Link href="/history">Browse all saved conversations</Link></p></section></aside><div className="report-column"><section className="card">{selected?<><h2>{detail.data?.title||'Conversation'}</h2><Button variant="outline" disabled={busy} onClick={()=>void mutate('delete')}>Delete conversation</Button>{detail.error&&<p role="alert">{detail.error}</p>}{detail.data?.messages.map(m=><article key={m.id} className="assistant-message"><p className="eyebrow">{m.role==='user'?'You':'Market Assistant'} · {formatPacific(m.created_at)}</p><p style={{whiteSpace:'pre-wrap'}}>{m.text??'Saved answer is unavailable under current source access.'}</p>{m.text&&<EvidenceList items={m.evidence}/>}</article>)}{detail.data?.cursor&&<p>Older messages and additional pages are available in History.</p>}<form onSubmit={e=>{e.preventDefault();void mutate('send');}}><label htmlFor="assistant-message">Your question</label><textarea id="assistant-message" maxLength={4000} value={message} onChange={e=>setMessage(e.target.value)} rows={4}/><Button type="submit" disabled={busy||waiting||!message.trim()}>Send question</Button></form>{(waiting)&&<p role="status">Preparing your answer…</p>}{run.error&&runId&&<p role="alert">{run.error}</p>}{run.data?.message&&<p role="status">{run.data.message}</p>}{run.data?.finished_at&&<p className="muted">{run.data.model_id||'No model available'} · Tokens: {run.data.input_tokens??'unknown'} input / {run.data.output_tokens??'unknown'} output · Cost: {run.data.cost??'unknown'}</p>}{retryQuestion&&!waiting&&run.data?.status!=='completed'&&<Button variant="outline" disabled={busy} onClick={()=>void mutate('retry')}>Retry question</Button>}</>:<p>Create or select a private conversation to begin.</p>}{error&&<p role="alert">{error}</p>}</section></div></div>}</main></AppShell>;
}
