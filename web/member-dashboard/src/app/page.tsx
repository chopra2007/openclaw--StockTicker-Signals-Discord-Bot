'use client';
import {AppShell} from '@/components/app-shell';
import {useSession} from '@/components/session';
import {FeedPanel} from '@/components/feed-panel';
export default function Page(){const {member}=useSession();
 return <AppShell><main id="main" className="workspace"><div className="page-head"><h1 tabIndex={-1}>Market overview</h1><p>Live analyst calls and trade setups from the bot. Search any ticker above for a full research report.</p></div>
 <div className="home-grid">{member?.features.feed.enabled&&<FeedPanel key={'feed'+member.features.feed.version} feature="feed" accessKey={member.id+member.features.feed.version}/>}{member?.features.setups.enabled&&<FeedPanel key={'setups'+member.features.setups.version} feature="setups" accessKey={member.id+member.features.setups.version}/>}</div></main></AppShell>}
