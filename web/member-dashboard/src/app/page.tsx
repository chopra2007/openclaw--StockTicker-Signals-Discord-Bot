'use client';
import {useState} from 'react';
import {AppShell} from '@/components/app-shell';
import {useSession} from '@/components/session';
import {FeedPanel} from '@/components/feed-panel';
import {MarketStrip} from '@/components/market-strip';
import {RecordLine} from '@/components/record-line';
type Tab='alerts'|'setups'|'feed';
const LABEL:Record<Tab,string>={alerts:'Alerts',setups:'Setups',feed:'Analyst calls'};
export default function Page(){const {member}=useSession();const [tab,setTab]=useState<Tab>('alerts');
 const feed=member?.features.feed.enabled,setups=member?.features.setups.enabled;
 const tabs=([feed&&'alerts',setups&&'setups',feed&&'feed'] as const).filter(Boolean) as Tab[];
 return <AppShell><main id="main" className="workspace"><div className="page-head"><h1 tabIndex={-1}>Overview</h1><p>Live alerts, trade setups and analyst calls. Search any ticker for a full report.</p></div>
 <MarketStrip/>{member?.features.setups.enabled&&<RecordLine/>}
 {tabs.length>1&&<div className="segmented" role="group" aria-label="Show">{tabs.map(t=><button key={t} type="button" aria-pressed={tab===t} onClick={()=>setTab(t)}>{LABEL[t]}</button>)}</div>}
 {member&&<div className="home" data-tab={tab}>
  {feed&&<FeedPanel key={'alerts'+member.features.feed.version} feature="alerts" accessKey={member.id+member.features.feed.version}/>}
  <div className="home-grid">{setups&&<FeedPanel key={'setups'+member.features.setups.version} feature="setups" accessKey={member.id+member.features.setups.version}/>}{feed&&<FeedPanel key={'feed'+member.features.feed.version} feature="feed" accessKey={member.id+member.features.feed.version}/>}</div>
 </div>}</main></AppShell>}
