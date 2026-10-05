'use client';
import {useEffect,useState} from 'react';
import {api,ApiError,initialResearch,discardInitialResearch} from './api';
import {type ResearchRequest} from './contracts';
export function useResearch(requestId:string|null,accessKey:string){
 const key=requestId+accessKey;
 const [state,setState]=useState<{key:string;data:ResearchRequest|null;error:string}>(()=>({key,data:initialResearch(requestId),error:''}));
 useEffect(()=>{discardInitialResearch(requestId);let closed=false,busy=false,again=false,timer:ReturnType<typeof setTimeout>|undefined;const controller=new AbortController();
  const poll=async()=>{if(closed||busy||document.hidden||!requestId)return;busy=true;let pending=false;
   try{const next=await api<ResearchRequest>('/research/'+encodeURIComponent(requestId),{signal:controller.signal});if(!closed){setState({key,data:next,error:''});pending=Object.values(next.sections).some(s=>s.status==='queued'||s.status==='running');}}
   catch(e){if(!closed&&!(e instanceof DOMException&&e.name==='AbortError')){setState({key,data:null,error:e instanceof ApiError?e.message:'Unable to check current access.'});}}
   finally{busy=false;if(!closed){clearTimeout(timer);const immediately=again&&!document.hidden;again=false;timer=setTimeout(poll,immediately?0:pending?2000:15000);}}
  };
  const focus=()=>{clearTimeout(timer);if(busy&&!document.hidden)again=true;else void poll();};void poll();window.addEventListener('focus',focus);document.addEventListener('visibilitychange',focus);
  return()=>{closed=true;controller.abort();clearTimeout(timer);window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',focus);};
 },[requestId,accessKey,key]);
 return state.key===key?{data:state.data,error:state.error}:{data:null,error:''};
}
