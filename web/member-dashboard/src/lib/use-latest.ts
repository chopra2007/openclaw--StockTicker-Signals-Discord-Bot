"use client";
import {useEffect,useState} from 'react';
import {api} from './api';
import type {LatestCard} from './contracts';

/** Newest cards for one panel. Refreshes every 30 s; a failed refresh keeps the last good list. */
export function useLatest(feature:'feed'|'setups'|'alerts',accessKey:string){
 const [state,setState]=useState<{key:string;cards:LatestCard[]|null;failed:boolean}>({key:'',cards:null,failed:false});
 const key=feature+accessKey;
 useEffect(()=>{let closed=false,timer:ReturnType<typeof setTimeout>|undefined;const controller=new AbortController();
  const poll=async()=>{if(closed||document.hidden)return;
   try{const page=await api<{cards:LatestCard[]}>('/'+feature+'/latest',{signal:controller.signal});if(!closed)setState({key,cards:page.cards,failed:false});}
   catch{if(!closed)setState(s=>({key,cards:s.key===key?s.cards:null,failed:true}));}
   finally{if(!closed){clearTimeout(timer);timer=setTimeout(poll,30000);}}};
  const wake=()=>{clearTimeout(timer);void poll();};void poll();document.addEventListener('visibilitychange',wake);
  return()=>{closed=true;controller.abort();clearTimeout(timer);document.removeEventListener('visibilitychange',wake);};
 },[feature,key]);
 return state.key===key?state:{key,cards:null,failed:false};
}
