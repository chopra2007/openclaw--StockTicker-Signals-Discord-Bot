'use client';
import {useFeed} from '@/lib/use-feed';
import {labels} from '@/lib/contracts';
import {formatPacific} from '@/lib/time';
import {FeedCard} from './feed-card';
import {SetupCard} from './setup-card';
export function FeedPanel({feature,accessKey}:{feature:'feed'|'setups';accessKey:string}){const {cards,sources,error}=useFeed(feature,accessKey);return <section className="card" id={feature}><div className="section-heading"><h2>{labels[feature]}</h2><span className="small muted">{cards.length} {cards.length===1?'observation':'observations'}</span></div><p className="muted">{feature==='feed'?'Permitted observations, with their original context.':'Entry, target and invalidation are separate from expected move estimates.'}</p>{error&&<p role="status">{error}</p>}{!cards.length&&!error&&<div className="empty-state">No eligible observations are available.</div>}{cards.map(card=>feature==='feed'?<FeedCard key={card.id} card={card}/>:<SetupCard key={card.id} card={card}/>)}<details className="evidence"><summary>Source freshness</summary>{Object.values(sources).map(s=><p key={s.source}>{s.source.replaceAll('_',' ')} · {s.status}<br/><small>Checked {formatPacific(s.checked_at)} · Last success {formatPacific(s.succeeded_at)}</small></p>)}</details></section>}
