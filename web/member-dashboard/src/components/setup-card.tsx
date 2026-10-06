import Link from 'next/link';
import type {LatestCard} from '@/lib/contracts';
import {money,timeAgo} from '@/lib/format';
import {Direction} from './feed-card';
export function SetupCard({card}:{card:LatestCard}){const p=card.plan!;const entry=p.entry_low!=null&&p.entry_high!=null&&p.entry_low!==p.entry_high?money(p.entry_low)+' – '+money(p.entry_high):money(p.entry_low??p.entry_high??card.price);
 return <article className="item"><div className="item-head"><Link href={'/ticker/'+encodeURIComponent(card.ticker)} className="ticker">{card.ticker}</Link><Direction value={p.direction}/>{card.price!=null&&<span className="item-price">{money(card.price)}</span>}{card.score!=null&&<span className="pill pill-muted" title="Bot confidence, 0–100">Confidence {Math.round(card.score)}</span>}<span className="item-time">{timeAgo(card.observed_at)}</span></div>
 {card.text&&<p className="item-text">{card.text}</p>}
 <dl className="plan"><div><dt>Entry</dt><dd>{entry}</dd></div><div><dt>Stop</dt><dd className="down">{money(p.stop)}</dd></div><div><dt>Targets</dt><dd className="up">{p.targets.map(money).join(' · ')}</dd></div></dl></article>}
