import type {Evidence,Metric} from '@/lib/contracts';
import {timeAgo} from '@/lib/format';
export function Value({metric}:{metric:Metric|null}){return <span className="metric-value">{metric?.value==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(metric.value)}</span>}
export function SafeLink({url,children}:{url:string|null;children:React.ReactNode}){let safe=false;try{const parsed=new URL(url||'');safe=parsed.protocol==='https:'&&!parsed.username&&!parsed.password;}catch{}return safe?<a href={url!} target="_blank" rel="noreferrer noopener">{children}</a>:<span>{children}</span>}
/** Quiet "Sources" toggle: where each fact came from, nothing else. */
export function EvidenceList({items}:{items:Evidence[]}){if(!items.length)return null;return <details className="sources"><summary>Sources ({items.length})</summary><ul>{items.map(e=><li key={e.id}><p>{e.excerpt}</p><small><SafeLink url={e.url}>{e.source_id.replaceAll('-',' ')}</SafeLink>{e.observed_at?' · '+timeAgo(e.observed_at):''}</small></li>)}</ul></details>}
