'use client';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from '@/lib/api';
import {type ReportPage,type SavedReport,type ConversationPage,type SavedConversation,sections,labels} from '@/lib/contracts';
import {formatPacific} from '@/lib/time';
import {AppShell} from './app-shell';
import {useSession} from './session';
import {ResearchSection} from './research-section';
import {EvidenceList} from './research-details';
import {Button} from './ui/button';

/** Current access refresh replaces or clears every visible page, without work submission. */
export function useHistoryRead<T>(path:string|null,accessKey:string,interval=15000){
 const key=path+accessKey;
 const [state,setState]=useState<{key:string;data:T|null;error:string}>({key,data:null,error:''});
 useEffect(()=>{
  let closed=false,busy=false,again=false,delay=interval,timer:ReturnType<typeof setTimeout>|undefined;
  const controller=new AbortController();
  const read=async()=>{
   if(closed||busy||document.hidden||!path)return;busy=true;
   try{const data=await api<T>(path,{signal:controller.signal});delay=data&&typeof data==='object'&&'status' in data&&(data.status==='queued'||data.status==='running')?interval:15000;if(!closed)setState({key,data,error:''});}
   catch(e){if(!closed&&!(e instanceof DOMException&&e.name==='AbortError'))setState({key,data:null,error:e instanceof ApiError?e.message:'Unable to check current access.'});}
   finally{busy=false;if(!closed){clearTimeout(timer);const immediately=again&&!document.hidden;again=false;timer=setTimeout(read,immediately?0:delay);}}
  };
  const focus=()=>{clearTimeout(timer);if(busy&&!document.hidden)again=true;else void read();};
  void read();window.addEventListener('focus',focus);document.addEventListener('visibilitychange',focus);
  return()=>{closed=true;controller.abort();clearTimeout(timer);window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',focus);};
 },[path,accessKey,key,interval]);
 return state.key===key?state:{data:null,error:''};
}

export function HistoryList(){
 const {member}=useSession();
 const [resource,setResource]=useState<'reports'|'conversations'>('reports');
 const [cursor,setCursor]=useState<string|null>(null),[previous,setPrevious]=useState<(string|null)[]>([]);
 const [selected,setSelected]=useState<string|null>(null),[messageCursor,setMessageCursor]=useState<string|null>(null);
 const [revision,setRevision]=useState(0),[deleting,setDeleting]=useState(false),[deleteError,setDeleteError]=useState('');
 const deletion=useRef<AbortController|null>(null);
 useEffect(()=>()=>{deletion.current?.abort();},[]);
 const allowed=resource==='reports'||!!member?.features.assistant.enabled;
 const accessKey=member?.id+JSON.stringify(member?.features)+revision;
 const list=useHistoryRead<ReportPage|ConversationPage>(allowed?'/'+resource+(cursor?'?cursor='+encodeURIComponent(cursor):''):null,accessKey);
 const detail=useHistoryRead<SavedReport|SavedConversation>(allowed&&selected?'/'+resource+'/'+encodeURIComponent(selected)+(messageCursor?'?cursor='+encodeURIComponent(messageCursor):''):null,accessKey);
 const saved=detail.data&&'sections' in detail.data?detail.data:null;
 const conversation=detail.data&&'messages' in detail.data?detail.data:null;
 function choose(next:'reports'|'conversations'){setResource(next);setCursor(null);setPrevious([]);setSelected(null);setMessageCursor(null);setDeleteError('');}
 async function remove(){
  if(!selected||deleting)return;
  const identity=selected,current=new AbortController();deletion.current=current;
  setDeleting(true);setDeleteError('');setSelected(null);setMessageCursor(null);
  try{await api('/'+resource+'/'+encodeURIComponent(identity),{method:'DELETE',signal:current.signal});if(!current.signal.aborted)setRevision(r=>r+1);}
  catch(e){if(!current.signal.aborted)setDeleteError(e instanceof ApiError?e.message:'Unable to delete this item.');}
  finally{if(!current.signal.aborted)setDeleting(false);}
 }
 return <AppShell><main className="workspace" id="main">
  <div className="page-intro"><p className="eyebrow">PRIVATE TO YOUR ACCOUNT</p><h1 tabIndex={-1}>Your history</h1><p className="lede">Reopen the original research, with source access checked today.</p></div>
  <div className="section-heading"><Button variant="outline" onClick={()=>choose('reports')} aria-pressed={resource==='reports'}>Saved reports</Button>{member?.features.assistant.enabled&&<Button variant="outline" onClick={()=>choose('conversations')} aria-pressed={resource==='conversations'}>Conversations</Button>}</div>
  {deleteError&&<p role="alert">{deleteError}</p>}
  {!allowed?<p>Conversation access is unavailable.</p>:<div className="report-layout history-layout"><aside className="report-sidebar"><div className="card">
   <h2>{resource==='reports'?'Saved reports':'Conversations'}</h2>
   {list.error&&<p role="alert">{list.error}</p>}
   {!list.data&&!list.error&&<p role="status">Loading your history…</p>}
   {list.data?.items.length===0&&<p>{resource==='reports'?'No saved reports yet.':'No conversations yet.'}</p>}
   {list.data?.items.map(item=><div className="filing" key={item.id}><p>{'ticker' in item?item.ticker||'Saved report':item.title||'Conversation'}</p><p className="small">{formatPacific(item.created_at)}</p><Button variant="outline" aria-label={(resource==='reports'?'Open saved report':'Open conversation')+' '+formatPacific(item.created_at)} onClick={()=>{setSelected(item.id);setMessageCursor(null);setDeleteError('');}}>Open</Button></div>)}
   <div className="section-heading">{previous.length>0&&<Button variant="outline" onClick={()=>{setCursor(previous[previous.length-1]);setPrevious(x=>x.slice(0,-1));}}>Previous page</Button>}{list.data?.cursor&&<Button variant="outline" onClick={()=>{setPrevious(x=>[...x,cursor]);setCursor(list.data!.cursor);}}>Next page</Button>}</div>
  </div></aside><div className="report-column">
   {selected&&<div className="card"><div className="section-heading"><h2>{saved?.ticker?saved.ticker+' saved report':resource==='reports'?'Saved report':'Saved conversation'}</h2><Button variant="outline" disabled={deleting} onClick={()=>void remove()}>{resource==='reports'?'Delete selected report':'Delete selected conversation'}</Button></div>{saved&&<p className="small">Saved {formatPacific(saved.saved_at)} · {saved.version?'Version '+saved.version:'No saved version'} · {saved.finalized?'Finished':'Not finalized'}</p>}</div>}
   {detail.error&&selected&&<p role="alert">{detail.error}</p>}
   {selected&&!detail.data&&!detail.error&&<p role="status">Loading saved content…</p>}
   {!selected&&<div className="card empty-state">Select an item to reopen it.</div>}
   {saved&&<>{saved.availability==='unavailable'&&<p className="notice">Saved content is unavailable under current access or source permissions.</p>}{sections.map(name=>saved.sections[name]?<div key={name}>{saved.annotations[name]?.map((notice,i)=><p key={i} className="notice">{labels[name]}: evidence {notice.status==='retracted'?'was retracted':'is unavailable'}{notice.recorded_at!==null?' · '+formatPacific(notice.recorded_at):''}. Dependent content is withheld.</p>)}<ResearchSection result={saved.sections[name]!}/></div>:null)}</>}
   {conversation&&<>{conversation.messages.map(message=><article className="card" key={message.id}><h3>{message.role==='user'?'You':'Market Assistant'}</h3><p className="small">{formatPacific(message.created_at)}</p><p>{message.text??'This message is unavailable under current source permissions.'}</p><EvidenceList items={message.evidence}/>{message.annotations.map((notice,i)=><p className="notice" key={i}>Evidence {notice.status==='retracted'?'was retracted':'is unavailable'}. Dependent content is withheld.</p>)}</article>)}{conversation.cursor&&<Button variant="outline" onClick={()=>setMessageCursor(conversation.cursor)}>Next messages</Button>}{messageCursor&&<Button variant="outline" onClick={()=>setMessageCursor(null)}>First messages</Button>}</>}
  </div></div>}
  <details className="card context-note"><summary>Account help: history and deletion</summary><p>Reports retain their original permitted results, including failed and unavailable sections. Refreshing research creates a separate saved report. Feed cleanup does not impose a time limit on your saved history.</p><p>Deleting a report removes your copy and stops pending delivery. Another member’s saved copy is separate. Deleting a conversation stops new messages from being delivered to it.</p><p>A source may withdraw access or require removal. That applies to every affected copy, including saved reports, charts and assistant messages. Restricted content is hidden or removed; it is never replaced with newer research. Your own source-free conversation text is retained separately.</p><p>Private backups must expire within 30 days, sooner or be excluded where a source requires it. Restores must apply current deletion records before any content is available. Deleted items must not reappear after restore.</p></details>
 </main></AppShell>;
}
