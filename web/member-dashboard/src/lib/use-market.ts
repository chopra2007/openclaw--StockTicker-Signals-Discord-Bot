"use client";
import {useEffect,useState,useSyncExternalStore} from 'react';
import {api,ApiError} from './api';
import type {StripPage,TickerQuote,WatchlistPage} from './contracts';

/** Fetch `path` now and every `ms` while the tab is visible. A failed refresh keeps the last good data. */
export function usePoll<T>(path:string|null,ms:number){
 const [state,setState]=useState<{path:string|null;data:T|null;failed:boolean}>({path:null,data:null,failed:false});
 useEffect(()=>{if(!path)return;let closed=false,timer:ReturnType<typeof setTimeout>|undefined;const controller=new AbortController();
  const poll=async()=>{if(closed||document.hidden)return;
   try{const data=await api<T>(path,{signal:controller.signal});if(!closed)setState({path,data,failed:false});}
   catch{if(!closed)setState(s=>({path,data:s.path===path?s.data:null,failed:true}));}
   finally{if(!closed){clearTimeout(timer);timer=setTimeout(poll,ms);}}};
  const wake=()=>{clearTimeout(timer);void poll();};void poll();document.addEventListener('visibilitychange',wake);
  return()=>{closed=true;controller.abort();clearTimeout(timer);document.removeEventListener('visibilitychange',wake);};
 },[path,ms]);
 return state.path===path?state:{path,data:null,failed:false};
}
export const useStrip=()=>usePoll<StripPage>('/market/strip',60000);

/** Current price and day change for the given tickers (only those the member may read come back). */
export function useQuotes(tickers:string[]){
 const key=[...new Set(tickers)].sort().join(',');
 const {data}=usePoll<{quotes:TickerQuote[]}>(key?'/market/quotes?symbols='+key:null,60000);
 return new Map((data?.quotes||[]).map(q=>[q.symbol,q] as const));
}

/* One shared watchlist for every star on the page. */
type Store={tickers:Set<string>|null;limit:number;full:boolean;busy:boolean};
let store:Store={tickers:null,limit:50,full:false,busy:false};
let loading=false;
let watchRevision=0,watchWrites=0;
const listeners=new Set<()=>void>();
const set=(next:Store)=>{store=next;listeners.forEach(l=>l());};
const subscribe=(l:()=>void)=>{listeners.add(l);return()=>{listeners.delete(l);};};
const apply=(page:WatchlistPage)=>set({tickers:new Set(page.items.map(i=>i.symbol)),limit:page.limit,full:false,busy:false});
function load(){if(loading||store.tickers)return;loading=true;const revision=watchRevision;api<WatchlistPage>('/watchlist').then(page=>{if(revision===watchRevision&&!watchWrites)apply(page);}).catch(()=>{}).finally(()=>{loading=false;});}
if(typeof window!=='undefined')window.addEventListener('member-clear',()=>{watchRevision++;store={tickers:null,limit:50,full:false,busy:false};listeners.forEach(l=>l());});
/** Reconcile remote membership with all stars. A read started before a local write cannot undo it. */
export function useWatchlistSnapshot(){
 const [state,setState]=useState<{data:WatchlistPage|null;failed:boolean}>({data:null,failed:false});
 useEffect(()=>{let closed=false,busy=false,timer:ReturnType<typeof setTimeout>|undefined;const controller=new AbortController();
  const poll=async()=>{if(closed||busy||document.hidden)return;busy=true;const revision=watchRevision;
   try{const page=await api<WatchlistPage>('/watchlist',{signal:controller.signal});if(!closed&&revision===watchRevision&&!watchWrites){apply(page);setState({data:page,failed:false});}}
   catch{if(!closed)setState(s=>({...s,failed:true}));}
   finally{busy=false;if(!closed){clearTimeout(timer);timer=setTimeout(poll,60000);}}};
  const wake=()=>{clearTimeout(timer);void poll();};void poll();document.addEventListener('visibilitychange',wake);
  return()=>{closed=true;controller.abort();clearTimeout(timer);document.removeEventListener('visibilitychange',wake);};
 },[]);return state;
}
export function useWatch(ticker:string){
 const s=useSyncExternalStore(subscribe,()=>store,()=>store);
 const [error,setError]=useState('');
 useEffect(()=>{load();},[s.tickers]);
 const watched=!!s.tickers?.has(ticker);
 const toggle=async()=>{
  if(watchWrites)return;watchWrites++;watchRevision++;setError('');set({...store,busy:true});
  try{
   if(watched){await api('/watchlist/'+encodeURIComponent(ticker),{method:'DELETE'});const next=new Set(store.tickers);next.delete(ticker);set({...store,tickers:next,full:false});}
   else apply(await api<WatchlistPage>('/watchlist/'+encodeURIComponent(ticker),{method:'PUT'}));
  }catch(e){if(e instanceof ApiError&&e.status===409){set({...store,full:true});setError('Watchlist is full ('+store.limit+' symbols).');}else setError(e instanceof ApiError?e.message:'Watchlist change failed. Try again.');}
  finally{watchWrites--;watchRevision++;set({...store,busy:false});}
 };
 return {ready:s.tickers!==null,watched,toggle,full:s.full,limit:s.limit,busy:s.busy,error};
}
/** The member's watched tickers (null until loaded); changes the moment a star is tapped anywhere. */
export const useWatched=()=>useSyncExternalStore(subscribe,()=>store.tickers,()=>null);
