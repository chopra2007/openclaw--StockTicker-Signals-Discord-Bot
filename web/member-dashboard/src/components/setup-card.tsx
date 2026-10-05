import type {FeedCard as Card} from '@/lib/contracts';
import {FeedCard} from './feed-card';
export function SetupCard({card}:{card:Card}){return <FeedCard card={card} setup/>}
