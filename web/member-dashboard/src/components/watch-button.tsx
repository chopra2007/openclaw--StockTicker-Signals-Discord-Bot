'use client';
import {useWatch} from '@/lib/use-market';
/** Star toggle: adds or removes a ticker from the member's watchlist. Hidden until the list has loaded. */
export function WatchButton({ticker,className}:{ticker:string;className?:string}){const {ready,watched,toggle,full,limit}=useWatch(ticker);if(!ready)return null;
 return <button type="button" className={'watch-button'+(className?' '+className:'')} aria-pressed={watched} aria-label={(watched?'Remove '+ticker+' from':'Add '+ticker+' to')+' watchlist'} title={full&&!watched?'Watchlist is full ('+limit+' tickers)':watched?'On your watchlist':'Add to watchlist'} onClick={()=>void toggle()}>
  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9l-5.2 2.8 1-5.9-4.3-4.1 5.9-.8z" fill={watched?'currentColor':'none'} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></svg></button>}
