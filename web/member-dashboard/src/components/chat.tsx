'use client';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from '@/lib/api';
import type {AssistantRun,ConversationRef,SavedConversation} from '@/lib/contracts';
import {SendIcon} from './icons';

type Line={id:string;role:'user'|'assistant';text:string|null};
const sleep=(ms:number,signal:AbortSignal)=>new Promise<void>((resolve,reject)=>{const t=setTimeout(resolve,ms);signal.addEventListener('abort',()=>{clearTimeout(t);reject(new DOMException('Aborted','AbortError'));},{once:true});});
/** The first question names the chat, like other chat apps: first line, at most 60 characters. */
export function titleFrom(text:string){const line=text.trim().split('\n')[0];if(line.length<=60)return line;const cut=line.slice(0,58);return cut.slice(0,cut.lastIndexOf(' ')>30?cut.lastIndexOf(' '):58)+'…';}

/** Answers are short lines; lines starting "- " become a bullet list. */
export function Answer({text}:{text:string}){
 const blocks:(string|string[])[]=[];
 for(const raw of text.split(/\n+/)){const line=raw.trim();if(!line)continue;
  if(/^[-•*]\s+/.test(line)){const item=line.replace(/^[-•*]\s+/,''),last=blocks[blocks.length-1];if(Array.isArray(last))last.push(item);else blocks.push([item]);}
  else blocks.push(line);}
 // Answers saved before 2026-10-06 put every point on one line: "Verdict. - Reason. - Reason."
 if(blocks.length===1&&typeof blocks[0]==='string'&&/[.!?] - /.test(blocks[0])){const [head,...rest]=blocks[0].split(/(?<=[.!?]) - /);return <><p>{head}</p><ul>{rest.map((r,i)=><li key={i}>{r}</li>)}</ul></>;}
 return <>{blocks.map((b,i)=>Array.isArray(b)?<ul key={i}>{b.map((x,j)=><li key={j}>{x}</li>)}</ul>:<p key={i}>{b}</p>)}</>;
}

export function Chat({conversationId,onConversation,ticker=null,suggestions,heading,autoFocus=false}:{conversationId:string|null;onConversation?:(ref:ConversationRef)=>void;ticker?:string|null;suggestions:string[];heading?:React.ReactNode;autoFocus?:boolean}){
 const [lines,setLines]=useState<Line[]>([]),[waiting,setWaiting]=useState(false),[failed,setFailed]=useState<string|null>(null),[draft,setDraft]=useState('');
 const [loadError,setLoadError]=useState('');
 const created=useRef<string|null>(null),current=useRef<string|null>(conversationId),work=useRef<AbortController|null>(null);
 const scroller=useRef<HTMLDivElement>(null),input=useRef<HTMLTextAreaElement>(null);
 useEffect(()=>()=>work.current?.abort(),[]);
 async function waitFor(id:string,run:AssistantRun,signal:AbortSignal){
  const started=Date.now();
  while((run.status==='queued'||run.status==='running')&&Date.now()-started<150000){await sleep(1000,signal);run=await api<AssistantRun>(`/conversations/${id}/runs/${run.id}`,{signal});}
  return run;
 }
 async function load(id:string,signal:AbortSignal){
  const saved=await api<SavedConversation>(`/conversations/${id}?tail=true`,{signal});
  setLines(saved.messages.map(m=>({id:m.id,role:m.role,text:m.text})));
  return saved;
 }
 // Opening a saved chat: show it, and pick up an answer that is still being written.
 useEffect(()=>{const previous=current.current;current.current=conversationId;
  if(conversationId&&conversationId===created.current&&conversationId===previous)return;  // Just created by send(): already shown.
  work.current?.abort();const controller=new AbortController();work.current=controller;
  void(async()=>{setFailed(null);setLoadError('');setWaiting(false);setLines([]);if(!conversationId)return;
   try{await load(conversationId,controller.signal);
    const run=await api<AssistantRun>(`/conversations/${conversationId}/runs/latest`,{signal:controller.signal}).catch(()=>null);
    if(run&&(run.status==='queued'||run.status==='running')){setWaiting(true);const done=await waitFor(conversationId,run,controller.signal);await load(conversationId,controller.signal);if(done.status!=='completed')setFailed('');}
   }catch(e){if(!controller.signal.aborted)setLoadError(e instanceof ApiError?e.message:'This chat couldn’t be opened.');}
   finally{if(!controller.signal.aborted)setWaiting(false);}})();
  return()=>controller.abort();
 },[conversationId]);
 useEffect(()=>{const el=scroller.current;if(el)el.scrollTop=el.scrollHeight;},[lines,waiting,failed]);
 useEffect(()=>{if(autoFocus)input.current?.focus();},[autoFocus]);
 async function send(text:string){
  text=text.trim();if(!text||waiting)return;
  work.current?.abort();const controller=new AbortController();work.current=controller;const {signal}=controller;
  setDraft('');setFailed(null);setWaiting(true);setLines(l=>[...l,{id:'local-'+Date.now(),role:'user',text}]);
  if(input.current)input.current.style.height='';
  try{
   let id=current.current;
   if(!id){const ref=await api<ConversationRef>('/conversations',{method:'POST',body:JSON.stringify({title:titleFrom(text)}),signal});id=ref.id;created.current=id;current.current=id;onConversation?.(ref);}
   const run=await waitFor(id,await api<AssistantRun>(`/conversations/${id}/messages`,{method:'POST',body:JSON.stringify({message:text,ticker_context:ticker}),signal}),signal);
   await load(id,signal);
   if(run.status!=='completed')setFailed(text);
  }catch{if(!signal.aborted)setFailed(text);}
  finally{if(!signal.aborted){setWaiting(false);input.current?.focus();}}
 }
 function onKey(e:React.KeyboardEvent<HTMLTextAreaElement>){if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send(draft);}}
 function grow(e:React.ChangeEvent<HTMLTextAreaElement>){setDraft(e.target.value);e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,160)+'px';}
 const empty=lines.length===0&&!waiting&&!loadError;
 return <div className="chat">
  <div className="chat-scroll" ref={scroller} aria-live="polite">
   {empty&&<div className="chat-empty">{heading}<div className="chips">{suggestions.map(s=><button key={s} type="button" className="chip" onClick={()=>void send(s)}>{s}</button>)}</div></div>}
   {loadError&&<p role="alert">{loadError}</p>}
   {lines.map(line=>line.role==='user'?<div key={line.id} className="bubble me">{line.text}</div>
    :<div key={line.id} className="bubble them">{line.text?<Answer text={line.text}/>:<p className="quiet">This answer is no longer available.</p>}</div>)}
   {waiting&&<div className="bubble them" aria-label="Writing an answer"><div className="typing"><span/><span/><span/></div></div>}
   {failed!==null&&!waiting&&<div className="bubble them failed" role="alert"><p>Couldn’t answer that right now.</p>{failed&&<button type="button" className="button button-ghost" onClick={()=>void send(failed)}>Try again</button>}</div>}
  </div>
  <form className="composer" onSubmit={e=>{e.preventDefault();void send(draft);}}>
   <label className="sr-only" htmlFor={'ask-'+(ticker||'all')}>Ask a question</label>
   <textarea id={'ask-'+(ticker||'all')} ref={input} rows={1} maxLength={4000} value={draft} onChange={grow} onKeyDown={onKey} enterKeyHint="send" placeholder={ticker?`Ask about ${ticker}…`:'Ask about any stock…'}/>
   <button type="submit" className="send" disabled={!draft.trim()||waiting} aria-label="Send"><SendIcon/></button>
  </form>
 </div>;
}
