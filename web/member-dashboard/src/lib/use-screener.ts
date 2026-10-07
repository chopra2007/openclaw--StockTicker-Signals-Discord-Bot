'use client';
import {useEffect,useState,useCallback,useRef} from 'react';
import {api,ApiError} from './api';
import type {LatestCard,TickerQuote} from './contracts';
type Snapshot={key:string;cards:LatestCard[]|null;quotes:TickerQuote[];checked:number|null;failed:boolean;busy:boolean};
/** Atomic cached reads, no work creation. Never overlap refreshes or retain a denied source. */
export function useScreener(universe:'setups'|'alerts',accessKey:string,enabled=true){
 const key=universe+accessKey;const [state,setState]=useState<Snapshot>({key:'',cards:null,quotes:[],checked:null,failed:false,busy:false});
 const read=useRef<()=>Promise<void>>(async()=>{});
 useEffect(()=>{if(!enabled)return;let closed=false,busy=false,timer:ReturnType<typeof setTimeout>|undefined;const controller=new AbortController();
  const poll=async()=>{if(closed||busy||document.hidden)return;busy=true;setState(s=>s.key===key?{...s,busy:true}:{key,cards:null,quotes:[],checked:null,failed:false,busy:true});
   try{const page=await api<{cards:LatestCard[]}>('/'+universe+'/latest',{signal:controller.signal});
    // Apply authorized source changes immediately: a quote outage cannot restore withdrawn cards.
    if(!closed)setState(s=>({...s,key,cards:page.cards,busy:true}));
    const symbols=[...new Set(page.cards.map(c=>c.ticker))].sort().join(',');
    const quotes=symbols?await api<{quotes:TickerQuote[]}>('/market/quotes?symbols='+symbols,{signal:controller.signal}):{quotes:[]};
    if(!closed)setState({key,cards:page.cards,quotes:quotes.quotes,checked:Date.now()/1000,failed:false,busy:false});
   }catch(e){if(!closed){const denied=e instanceof ApiError&&(e.status===401||e.status===403);setState(s=>({key,cards:!denied&&s.key===key?s.cards:null,quotes:!denied&&s.key===key?s.quotes:[],checked:s.key===key?s.checked:null,failed:true,busy:false}));}}
   finally{busy=false;if(!closed){clearTimeout(timer);timer=setTimeout(poll,30000);}}};
  read.current=poll;const wake=()=>{clearTimeout(timer);void poll();};void poll();document.addEventListener('visibilitychange',wake);
  return()=>{closed=true;controller.abort();clearTimeout(timer);document.removeEventListener('visibilitychange',wake);};
 },[universe,key,enabled]);
 const refresh=useCallback(()=>void read.current(),[]);
 return {...(state.key===key?state:{key,cards:null,quotes:[],checked:null,failed:false,busy:true}),refresh};
}
