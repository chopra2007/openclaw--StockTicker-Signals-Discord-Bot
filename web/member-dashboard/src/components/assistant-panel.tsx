'use client';
import {useState} from 'react';
import type {ConversationPage} from '@/lib/contracts';
import {AppShell} from './app-shell';
import {useSession} from './session';
import {useHistoryRead,formatDate} from './history-list';
import {Chat} from './chat';
import {Button} from './ui/button';

const SUGGESTIONS=['Is NVDA a buy for the next few weeks?','What’s driving TSLA this week?','What does a put/call ratio tell me?'];

export function AssistantPanel({ticker,conversation}:{ticker:string|null;conversation:string|null}){
 const {member}=useSession();
 const [selected,setSelected]=useState<string|null>(conversation),[revision,setRevision]=useState(0),[showList,setShowList]=useState(false);
 const allowed=!!member?.features.assistant.enabled;
 const list=useHistoryRead<ConversationPage>(allowed?'/conversations':null,member?.id+JSON.stringify(member?.features)+revision);
 const open=(id:string|null)=>{setSelected(id);setShowList(false);};
 return <AppShell><main id="main" className="workspace">
  {!allowed?<div className="card empty-state">The assistant is turned off for your account.</div>:
  <div className={'assistant-page'+(showList?' show-list':'')}>
   <nav className="chat-list" aria-label="Your chats">
    <Button onClick={()=>open(null)}>New chat</Button>
    {list.data&&list.data.items.length>0&&<small>Recent</small>}
    {list.data?.items.map(c=><button key={c.id} type="button" className="row" aria-current={selected===c.id} onClick={()=>open(c.id)}><span className="row-title">{c.title}</span><span className="row-date">{formatDate(c.created_at)}</span></button>)}
   </nav>
   <section className="chat-main" aria-label="Chat">
    {!!list.data?.items.length&&<Button variant="ghost" className="chats-toggle" onClick={()=>setShowList(true)}>‹ All chats</Button>}
    <Chat key={ticker||'all'} conversationId={selected} ticker={ticker} autoFocus suggestions={ticker?[`Is ${ticker} a buy right now?`,`What’s driving ${ticker} this week?`,`What are the risks for ${ticker}?`]:SUGGESTIONS}
     onConversation={ref=>{setSelected(ref.id);setRevision(r=>r+1);}}
     heading={<><h2>Ask about any stock</h2><p>Get the signal, trade plan and latest news in plain English.</p></>}/>
   </section>
  </div>}
 </main></AppShell>;
}
