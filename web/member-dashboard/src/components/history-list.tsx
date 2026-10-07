'use client';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from '@/lib/api';
import {type ReportPage,type SavedReport,type ConversationPage,type SavedConversation,sections,labels} from '@/lib/contracts';
import {formatShort} from '@/lib/time';
import {money} from '@/lib/format';
import {AppShell} from './app-shell';
import {useSession} from './session';
import {ResearchSection} from './research-section';
import {EvidenceList} from './research-details';
import {Button} from './ui/button';
import {Answer} from './chat';

/** Current access refresh replaces or clears every visible page, without work submission. */
export function useHistoryRead<T>(path:string|null,accessKey:string,interval=15000){
 const key=path+accessKey;
 const [state,setState]=useState<{key:string;data:T|null;error:string}>({key,data:null,error:''});
 useEffect(()=>{
  let closed=false,busy=false,again=false,delay=interval,timer:ReturnType<typeof setTimeout>|undefined;
  const controller=new AbortController();
  const read=async()=>{
   if(closed||busy||document.hidden||!path)return;busy=true;
   try{const data=await api<T>(path,{signal:controller.signal});
    const pending=data&&typeof data==='object'&&(('status' in data&&(data.status==='queued'||data.status==='running'))||('availability' in data&&data.availability==='pending'));
    delay=pending?interval:15000;if(!closed)setState({key,data,error:''});}
   catch(e){if(!closed&&!(e instanceof DOMException&&e.name==='AbortError'))setState({key,data:null,error:e instanceof ApiError?e.message:'Unable to check current access.'});}
   finally{busy=false;if(!closed){clearTimeout(timer);const immediately=again&&!document.hidden;again=false;timer=setTimeout(read,immediately?0:delay);}}
  };
  const focus=()=>{clearTimeout(timer);if(busy&&!document.hidden)again=true;else void read();};
  void read();window.addEventListener('focus',focus);document.addEventListener('visibilitychange',focus);
  return()=>{closed=true;controller.abort();clearTimeout(timer);window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',focus);};
 },[path,accessKey,key,interval]);
 return state.key===key?state:{data:null,error:''};
}

const dayKey=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'});
const dayName=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric'});
const clockName=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',hour:'numeric',minute:'2-digit'});
/** "Oct 6" (Pacific). */
export const formatDate=(epoch:number)=>dayName.format(new Date(epoch*1000));
type Ref=ReportPage['items'][number];
/** Reports of one ticker made on one Pacific day share a row, in the order they were first listed. */
function groupReports(items:Ref[]){
 const groups=new Map<string,Ref[]>();
 for(const item of items){const key=(item.ticker||'')+'|'+dayKey.format(new Date(item.created_at*1000));groups.set(key,[...(groups.get(key)||[]),item]);}
 return [...groups];
}
const signalName={bullish:'Bullish',bearish:'Bearish',neutral:'Neutral',unclear:'Neutral'} as const;
function Signal({direction}:{direction:Ref['direction']}){
 return direction?<span className={'pill row-pill '+(direction==='bullish'?'pill-up':direction==='bearish'?'pill-down':'pill-flat')}>{signalName[direction]}</span>:null;
}
function ReportRow({item,selected,onOpen,sub=false}:{item:Ref;selected:boolean;onOpen:(id:string)=>void;sub?:boolean}){
 const when=sub?clockName.format(new Date(item.created_at*1000)):formatShort(item.created_at);
 const second=sub?(item.price!=null?money(item.price):''):(item.price!=null?money(item.price)+' · ':'')+when;
 return <li><button type="button" aria-current={selected||undefined} aria-label={'Open saved report '+(item.ticker||'')+', '+formatShort(item.created_at)} onClick={()=>onOpen(item.id)}>
  <span className="row-title">{sub?when:item.ticker||'Saved report'}</span><Signal direction={item.direction}/>{second&&<span className="row-time">{second}</span>}<span className="chevron" aria-hidden="true">›</span></button></li>;
}
function ReportGroup({id,items,selected,open,onToggle,onOpen}:{id:string;items:Ref[];selected:string|null;open:boolean;onToggle:(id:string)=>void;onOpen:(id:string)=>void}){
 const first=items[0],today=dayKey.format(new Date())===dayKey.format(new Date(first.created_at*1000));
 const label=items.length+' reports '+(today?'today':'on '+formatDate(first.created_at));
 return <li className="history-group"><button type="button" aria-expanded={open} aria-label={(first.ticker||'Saved report')+', '+label} onClick={()=>onToggle(id)}>
  <span className="row-title">{first.ticker||'Saved report'} · {label}</span><Signal direction={first.direction}/>
  <span className="row-time">Latest {first.price!=null?money(first.price)+' · ':''}{formatShort(first.created_at)}</span><span className="chevron" aria-hidden="true">›</span></button>
  {open&&<ul className="history-sub">{items.map(item=><ReportRow key={item.id} item={item} sub selected={selected===item.id} onOpen={onOpen}/>)}</ul>}</li>;
}

export function HistoryList(){
 const {member}=useSession();
 const [resource,setResource]=useState<'reports'|'conversations'>('reports');
 const [cursor,setCursor]=useState<string|null>(null),[previous,setPrevious]=useState<(string|null)[]>([]);
 const [selected,setSelected]=useState<string|null>(null),[messageCursor,setMessageCursor]=useState<string|null>(null);
 const [revision,setRevision]=useState(0),[deleting,setDeleting]=useState(false),[deleteError,setDeleteError]=useState(''),[confirming,setConfirming]=useState(false),[expanded,setExpanded]=useState<string[]>([]);
 const deletion=useRef<AbortController|null>(null);
 useEffect(()=>()=>{deletion.current?.abort();},[]);
 const allowed=resource==='reports'||!!member?.features.assistant.enabled;
 const accessKey=member?.id+JSON.stringify(member?.features)+revision;
 const list=useHistoryRead<ReportPage|ConversationPage>(allowed?'/'+resource+(cursor?'?cursor='+encodeURIComponent(cursor):''):null,accessKey);
 const detail=useHistoryRead<SavedReport|SavedConversation>(allowed&&selected?'/'+resource+'/'+encodeURIComponent(selected)+(messageCursor?'?cursor='+encodeURIComponent(messageCursor):''):null,accessKey,1000);
 const saved=detail.data&&'sections' in detail.data?detail.data:null;
 const conversation=detail.data&&'messages' in detail.data?detail.data:null;
 function choose(next:'reports'|'conversations'){setResource(next);setCursor(null);setPrevious([]);setSelected(null);setMessageCursor(null);setDeleteError('');setConfirming(false);}
 async function remove(){
  if(!selected||deleting)return;
  const identity=selected,current=new AbortController();deletion.current=current;
  setDeleting(true);setConfirming(false);setDeleteError('');setSelected(null);setMessageCursor(null);
  try{await api('/'+resource+'/'+encodeURIComponent(identity),{method:'DELETE',signal:current.signal});if(!current.signal.aborted)setRevision(r=>r+1);}
  catch(e){if(!current.signal.aborted)setDeleteError(e instanceof ApiError?e.message:'Unable to delete this item.');}
  finally{if(!current.signal.aborted)setDeleting(false);}
 }
 const open=(id:string)=>{setSelected(id);setMessageCursor(null);setDeleteError('');setConfirming(false);};
 const toggle=(id:string)=>setExpanded(x=>x.includes(id)?x.filter(y=>y!==id):[...x,id]);
 const kind=resource==='reports'?'report':'chat';
 return <AppShell><main className="workspace" id="main">
  <div className="page-intro"><h1 tabIndex={-1}>History</h1><p className="lede">Your saved reports and chats. Only you can see them.</p></div>
  {member?.features.assistant.enabled&&<div className="switch" role="group" aria-label="Show">{(['reports','conversations'] as const).map(r=><button key={r} type="button" aria-pressed={resource===r} onClick={()=>choose(r)}>{r==='reports'?'Reports':'Chats'}</button>)}</div>}
  {deleteError&&<p role="alert">{deleteError}</p>}
  {!allowed?<p>Chats are not available on your account.</p>:<div className="history-layout" data-open={selected?'':undefined}><aside className="history-index">
   {list.error&&<p role="alert">{list.error}</p>}
   {!list.data&&!list.error&&<div className="skeleton-list" aria-label="Loading"><span/><span/><span/></div>}
   {list.data?.items.length===0&&<p className="panel-empty">{resource==='reports'?'No saved reports yet. Search a ticker to create one.':'No chats yet. Ask the Assistant a question to start one.'}</p>}
   {!!list.data?.items.length&&<ul className="history-rows">{resource==='reports'?groupReports(list.data.items as Ref[]).map(([key,items])=>items.length>1?<ReportGroup key={key} id={key} items={items} selected={selected} open={expanded.includes(key)} onToggle={toggle} onOpen={open}/>:<ReportRow key={key} item={items[0]} selected={selected===items[0].id} onOpen={open}/>)
    :list.data.items.map(item=><li key={item.id}><button type="button" aria-current={selected===item.id||undefined} aria-label={'Open conversation '+('title' in item?item.title||'':'')+', '+formatShort(item.created_at)} onClick={()=>open(item.id)}>
    <span className="row-title">{'title' in item?item.title||'Chat':''}</span><span className="row-time">{formatShort(item.created_at)}</span><span className="chevron" aria-hidden="true">›</span></button></li>)}</ul>}
   {(previous.length>0||list.data?.cursor)&&<div className="pager">{previous.length>0&&<Button variant="ghost" onClick={()=>{setCursor(previous[previous.length-1]);setPrevious(x=>x.slice(0,-1));}}>Newer</Button>}{list.data?.cursor&&<Button variant="ghost" onClick={()=>{setPrevious(x=>[...x,cursor]);setCursor(list.data!.cursor);}}>Older</Button>}</div>}
  </aside><div className="history-detail">
   {selected&&<div className="detail-head"><Button variant="ghost" className="back" onClick={()=>{setSelected(null);setMessageCursor(null);setConfirming(false);}}>‹ {resource==='reports'?'Reports':'Chats'}</Button>
    <div><h2>{saved?.ticker?saved.ticker+' report':conversation?.title||(resource==='reports'?'Report':'Chat')}</h2>{saved&&<p className="small">Saved {formatShort(saved.saved_at)}</p>}</div>
    <div className="detail-actions">{confirming?<><span className="small">Delete this {kind} for good?</span><Button variant="ghost" onClick={()=>setConfirming(false)}>Cancel</Button><Button variant="ghost" className="danger" disabled={deleting} onClick={()=>void remove()}>Yes, delete</Button></>
     :<Button variant="ghost" className="danger" disabled={deleting} onClick={()=>setConfirming(true)}>Delete {kind}</Button>}</div></div>}
   {detail.error&&selected&&<p role="alert">{detail.error}</p>}
   {selected&&!detail.data&&!detail.error&&<div className="panel"><div className="skeleton-list" aria-label="Loading"><span/><span/><span/></div></div>}
   {!selected&&<div className="panel panel-empty history-pick">Pick a {kind} to read it here.</div>}
   {saved&&<div className="report-grid">{saved.availability==='unavailable'&&<p className="notice">This report can no longer be shown under current access.</p>}{sections.map(name=>saved.sections[name]?<div key={name}>{saved.annotations[name]?.map((notice,i)=><p key={i} className="notice">{labels[name]}: a source {notice.status==='retracted'?'was withdrawn':'is no longer available'}{notice.recorded_at!==null?' ('+formatShort(notice.recorded_at)+')':''}, so the parts that used it are hidden.</p>)}<ResearchSection result={saved.sections[name]!}/></div>:null)}</div>}
   {conversation&&<div className="panel history-chat">{messageCursor&&<Button variant="ghost" onClick={()=>setMessageCursor(null)}>Back to the start</Button>}
    {conversation.messages.map(message=><div key={message.id} className={'bubble '+(message.role==='user'?'me':'them')}>{message.text==null?'This message can no longer be shown under current access.':message.role==='user'?message.text:<Answer text={message.text}/>}
     <EvidenceList items={message.evidence}/>{message.annotations.map((notice,i)=><p className="small" key={i}>A source {notice.status==='retracted'?'was withdrawn':'is no longer available'}, so parts are hidden.</p>)}
     <time className="bubble-time">{formatShort(message.created_at)}</time></div>)}
    {conversation.cursor&&<Button variant="ghost" onClick={()=>setMessageCursor(conversation.cursor)}>Later messages</Button>}</div>}
  </div></div>}
  <p className="foot-note">Deleting removes your copy for good. A refresh saves a new report and keeps the old one.</p>
 </main></AppShell>;
}
