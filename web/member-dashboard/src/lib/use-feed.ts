"use client";
import {useEffect,useState} from 'react';
import {api,ApiError} from './api';
import type {FeedCard,FeedPage,SourceFreshness} from './contracts';
export function useFeed(feature:'feed'|'setups',accessKey:string){
 const key=feature+accessKey;
 const [state,setState]=useState<{key:string;cards:FeedCard[];sources:Record<string,SourceFreshness>;error:string}>({key:'',cards:[],sources:{},error:''});
 useEffect(()=>{let closed=false,busy=false,cursor:string|undefined,timer:ReturnType<typeof setTimeout>|undefined;let items=new Map<string,FeedCard>();const controller=new AbortController();
  const poll=async()=>{if(closed||busy||document.hidden)return;busy=true;let delay=15000;
   try{let pages=0,more=true;while(more&&!closed&&pages++<20){const page=await api<FeedPage>('/'+feature+(cursor?'?cursor='+encodeURIComponent(cursor):''),{signal:controller.signal});if(closed)return;
     if(!cursor)items=new Map();for(const row of page.records){if(row.operation==='delete')items.delete(row.id);else items.set(row.id,row);}
     cursor=page.cursor;more=page.has_more;const sources=Object.fromEntries(page.sources.map(s=>[s.source,s]));
     const cards=[...items.values()].map(card=>({...card,stale:card.stale||!!(card.source&&sources[card.source]?.status!=='available')}));setState({key,cards,sources,error:''});
   }if(more)delay=0;
   }catch(e){if(!closed&&!(e instanceof DOMException&&e.name==='AbortError')){items.clear();cursor=undefined;const reset=e instanceof ApiError&&e.status===409&&e.code==='snapshot_reset';setState({key,cards:[],sources:{},error:reset?'Refreshing the feed snapshot…':e instanceof ApiError?e.message:'Feed unavailable.'});if(reset)delay=0;}}
   finally{busy=false;if(!closed){clearTimeout(timer);timer=setTimeout(poll,delay);}}
  };
  const focus=()=>{clearTimeout(timer);void poll();};void poll();window.addEventListener('focus',focus);document.addEventListener('visibilitychange',focus);
  return()=>{closed=true;controller.abort();clearTimeout(timer);window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',focus);};
 },[feature,accessKey,key]);return state.key===key?state:{cards:[],sources:{},error:''};
}
