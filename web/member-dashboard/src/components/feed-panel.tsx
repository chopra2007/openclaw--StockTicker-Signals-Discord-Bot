'use client';
import {useEffect,useState} from 'react';
import {useLatest} from '@/lib/use-latest';
import {useQuotes} from '@/lib/use-market';
import {AlertCard} from './alert-card';
import {FeedCard} from './feed-card';
import {SetupCard} from './setup-card';
const copy={alerts:{title:'Alerts',sub:'Several analysts posting about the same stock at once. Newest first.',empty:'No alerts in the last 7 days. New ones appear here within a minute of posting.'},
 feed:{title:'Analyst calls',sub:'What analysts are posting, newest first.',empty:'No analyst calls in the last 7 days.'},
 setups:{title:'Trade setups',sub:'The bot’s latest alerts with entry, stop and targets.',empty:'No trade setups in the last 7 days.'}};
function useNow(){const [now,setNow]=useState(()=>Date.now()/1000);useEffect(()=>{const t=setInterval(()=>setNow(Date.now()/1000),30000);return()=>clearInterval(t);},[]);return now;}
export function FeedPanel({feature,accessKey}:{feature:'feed'|'setups'|'alerts';accessKey:string}){const {cards,failed}=useLatest(feature,accessKey);const c=copy[feature];const now=useNow();const quotes=useQuotes((cards||[]).map(x=>x.ticker));const [all,setAll]=useState(false);const first=feature==='alerts'?6:8;const shown=cards&&!all?cards.slice(0,first):cards;
 return <section className={'panel panel-'+feature} id={feature} aria-live={feature==='alerts'?'polite':undefined}><header className="panel-head"><div><h2>{c.title}</h2><p>{c.sub}</p></div>{failed&&cards&&<span className="pill pill-muted">Reconnecting…</span>}</header>
 {cards===null?(failed?<p className="panel-empty">Couldn’t load right now. Retrying shortly.</p>:<div className="skeleton-list" aria-label="Loading"><span/><span/><span/></div>)
  :cards.length===0?<p className="panel-empty">{c.empty}</p>
  :<><ul className={feature==='alerts'?'alert-list':'card-list'}>{shown!.map(card=><li key={card.id}>{feature==='alerts'?(card.group&&<AlertCard card={card} now={now} quote={quotes.get(card.ticker)}/>):feature==='feed'?<FeedCard card={card}/>:<SetupCard card={card} quote={quotes.get(card.ticker)}/>}</li>)}</ul>{cards.length>first&&<button type="button" className="show-more" aria-expanded={all} onClick={()=>setAll(a=>!a)}>{all?'Show fewer':`Show all ${cards.length}`}</button>}</>}
 </section>}
