'use client';
import {useLatest} from '@/lib/use-latest';
import {FeedCard} from './feed-card';
import {SetupCard} from './setup-card';
const copy={feed:{title:'Analyst calls',sub:'What analysts are saying, newest first.',empty:'No analyst calls in the last 7 days.'},
 setups:{title:'Trade setups',sub:'Recent bot alerts with entry, stop and targets.',empty:'No trade setups in the last 7 days.'}};
export function FeedPanel({feature,accessKey}:{feature:'feed'|'setups';accessKey:string}){const {cards,failed}=useLatest(feature,accessKey);const c=copy[feature];
 return <section className="panel" id={feature}><header className="panel-head"><div><h2>{c.title}</h2><p>{c.sub}</p></div>{failed&&cards&&<span className="pill pill-muted">Reconnecting…</span>}</header>
 {cards===null?(failed?<p className="panel-empty">Couldn’t load right now. Retrying shortly.</p>:<div className="skeleton-list" aria-label="Loading"><span/><span/><span/></div>)
  :cards.length===0?<p className="panel-empty">{c.empty}</p>
  :<ul className="card-list">{cards.map(card=><li key={card.id}>{feature==='feed'?<FeedCard card={card}/>:<SetupCard card={card}/>}</li>)}</ul>}
 </section>}
