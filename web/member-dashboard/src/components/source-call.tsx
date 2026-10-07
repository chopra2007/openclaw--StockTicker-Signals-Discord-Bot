import type {LatestCard} from '@/lib/contracts';
import {formatPacific} from '@/lib/time';
import {SafeLink} from './research-details';
type Call=NonNullable<LatestCard['group']>['calls'][number];
export function SourceCall({call}:{call:Call}){
 const stamp=call.posted_at??call.observed_at;
 return <><span className={'view view-'+call.view}>{call.view[0].toUpperCase()+call.view.slice(1)}</span><span className="who">@{call.analyst}</span>
 <p className="screen-note">{stamp?<time dateTime={new Date(stamp*1000).toISOString()}>{call.posted_at?'Posted':'Collected'} {formatPacific(stamp)}</time>:'Post time not recorded'}</p>
 <p className={call.reason==='reason not stated'?'no-reason':undefined}>{call.reason==='reason not stated'?'No reason given':call.reason}</p>
 {call.url&&<SafeLink url={call.url}>Original post ↗</SafeLink>}
 {call.image_urls?.map((url,i)=><details className="source-chart" key={url}><summary>Attached chart {i+1}</summary><SafeLink url={url}>
 {/* Original public attachment, no image proxy or generated interpretation. */}
 {/* eslint-disable-next-line @next/next/no-img-element */}
 <img src={url} alt={'Original chart attached by @'+call.analyst} loading="lazy" decoding="async" referrerPolicy="no-referrer"/>
 </SafeLink><p className="screen-note">Source image; an attached chart alone does not establish the analyst’s trading direction.</p></details>)}</>;
}
