'use client';
import {createContext,useCallback,useContext,useEffect,useRef,useState} from 'react';
import {usePathname,useRouter} from 'next/navigation';
import {api,clearAccess,ApiError,accessGeneration} from '@/lib/api';
import type {CurrentMember} from '@/lib/contracts';
import {LoadingScreen,OfflineScreen} from './status-screen';
const OFFLINE='Your connection dropped or the server is busy. Nothing is lost, and we’ll keep trying on our own.';
const Session=createContext<{member:CurrentMember|null;refresh:()=>Promise<void>}>({member:null,refresh:async()=>{}});
export const useSession=()=>useContext(Session);
export function SessionProvider({children}:{children:React.ReactNode}){
 const [member,setMember]=useState<CurrentMember|null>(null),[error,setError]=useState('');
 const router=useRouter(),path=usePathname(),busy=useRef(false),alive=useRef(true);
 const publicRoute=['/login','/join','/reset'].includes(path);
 const refresh=useCallback(async()=>{
  if(busy.current)return;busy.current=true;const stamp=accessGeneration();
  try{
   const data=await api<CurrentMember>('/me');
   if(alive.current&&stamp===accessGeneration()){setMember(data);setError('');}
  }catch(e){
   const aborted=e instanceof DOMException&&e.name==='AbortError';
   if(alive.current&&stamp===accessGeneration()&&!aborted&&!(e instanceof ApiError&&e.status===401)){
    setMember(null);setError(e instanceof ApiError?e.message:OFFLINE);
   }
  }finally{busy.current=false;}
 },[]);
 useEffect(()=>{alive.current=true;const clear=()=>{setMember(null);setError('');if(!publicRoute)router.replace('/login');};window.addEventListener('member-clear',clear);return()=>{alive.current=false;window.removeEventListener('member-clear',clear);};},[publicRoute,router]);
 useEffect(()=>{if(publicRoute)return;const initial=setTimeout(()=>void refresh(),0);const current=()=>{if(!document.hidden)void refresh();};const timer=setInterval(current,15000);window.addEventListener('focus',current);document.addEventListener('visibilitychange',current);return()=>{clearTimeout(initial);clearInterval(timer);window.removeEventListener('focus',current);document.removeEventListener('visibilitychange',current);};},[publicRoute,refresh]);
 useEffect(()=>{document.querySelector<HTMLElement>('h1')?.focus();},[path,member?.id]);
 return <Session.Provider value={{member,refresh}}>{publicRoute?children:member?children:error?<OfflineScreen title={error===OFFLINE?'Couldn’t reach Market Edge':'Couldn’t load your workspace'} message={error} onRetry={()=>void refresh()}/>:<LoadingScreen/>}</Session.Provider>;
}
export async function logout(){try{await api('/auth/logout',{method:'POST'});}finally{clearAccess();}}
