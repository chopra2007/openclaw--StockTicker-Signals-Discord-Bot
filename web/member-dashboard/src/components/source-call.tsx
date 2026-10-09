import type {LatestCard} from '@/lib/contracts';
import {formatPacific} from '@/lib/time';
import {SafeLink} from './research-details';
type Call=NonNullable<LatestCard['group']>['calls'][number];
/** "6 hours ago" style age; the exact time stays in the hover title. */
function ago(epoch:number){const s=Math.max(0,Date.now()/1000-epoch);if(s<60)return 'Just now';
 const [n,unit]=s<3600?[s/60,'minute']:s<86400?[s/3600,'hour']:[s/86400,'day'];const k=Math.floor(n);return k+' '+unit+(k===1?'':'s')+' ago'}
export function SourceCall({call}:{call:Call}){
 const stamp=call.posted_at??call.observed_at;
 return <><span className={'view view-'+call.view}>{call.view[0].toUpperCase()+call.view.slice(1)}</span><span className="who">@{call.analyst}</span>
 <p className="screen-note">{stamp?<time dateTime={new Date(stamp*1000).toISOString()} title={(call.posted_at?'Posted ':'Collected ')+formatPacific(stamp)}>{ago(stamp)}</time>:'Post time not recorded'}</p>
 <p className={call.reason==='reason not stated'?'no-reason':undefined}>{call.reason==='reason not stated'?'No reason given':call.reason}</p>
 {call.image_urls&&call.image_urls.length>0&&<div className="call-charts">{call.image_urls.map(url=><SafeLink key={url} url={url}>
  {/* Original public attachment, no image proxy or generated interpretation. */}
  {/* eslint-disable-next-line @next/next/no-img-element */}
  <img src={url} alt={'Original chart attached by @'+call.analyst} loading="lazy" decoding="async" referrerPolicy="no-referrer"/>
 </SafeLink>)}</div>}
 {call.url&&<span className="post-link"><SafeLink url={call.url}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>Original post</SafeLink></span>}</>;
}
