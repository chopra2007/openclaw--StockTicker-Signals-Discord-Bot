'use client';
import {useState} from 'react';
import {AppShell} from '@/components/app-shell';
import {useSession} from '@/components/session';
import {FeedPanel} from '@/components/feed-panel';
export default function Page(){const {member}=useSession();const [tab,setTab]=useState<'feed'|'setups'>('setups');
 const feed=member?.features.feed.enabled,setups=member?.features.setups.enabled;
 return <AppShell><main id="main" className="workspace"><div className="page-head"><h1 tabIndex={-1}>Overview</h1><p>Trade setups and analyst calls, updated live. Search a ticker for a full report.</p></div>
 {feed&&setups&&<div className="segmented" role="group" aria-label="Show">{(['setups','feed'] as const).map(t=><button key={t} type="button" aria-pressed={tab===t} onClick={()=>setTab(t)}>{t==='setups'?'Trade setups':'Analyst calls'}</button>)}</div>}
 <div className="home-grid" data-tab={tab}>{member&&setups&&<FeedPanel key={'setups'+member.features.setups.version} feature="setups" accessKey={member.id+member.features.setups.version}/>}{member&&feed&&<FeedPanel key={'feed'+member.features.feed.version} feature="feed" accessKey={member.id+member.features.feed.version}/>}</div></main></AppShell>}
