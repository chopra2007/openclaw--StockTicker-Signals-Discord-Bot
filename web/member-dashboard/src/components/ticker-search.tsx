'use client';
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {api,ApiError,primeResearch} from '@/lib/api';
import type {ResearchRequest} from '@/lib/contracts';
import {Button} from './ui/button';
export function TickerSearch(){const [busy,setBusy]=useState(false),[error,setError]=useState('');const router=useRouter();const controller=useRef<AbortController|null>(null),alert=useRef<HTMLParagraphElement>(null);
 useEffect(()=>()=>controller.current?.abort(),[]);
 async function submit(e:React.FormEvent<HTMLFormElement>){e.preventDefault();if(busy)return;setBusy(true);setError('');controller.current?.abort();const current=new AbortController();controller.current=current;const ticker=String(new FormData(e.currentTarget).get('ticker')||'').trim();
  try{const result=await api<ResearchRequest>('/research',{method:'POST',body:JSON.stringify({ticker,refresh:false}),signal:current.signal});if(!current.signal.aborted){primeResearch(result);router.push('/ticker/'+encodeURIComponent(result.ticker)+'?request='+encodeURIComponent(result.id));}}
  catch(e){if(!current.signal.aborted){setError(e instanceof ApiError?e.message:'Unable to request research.');setTimeout(()=>alert.current?.focus(),0);}}finally{if(!current.signal.aborted)setBusy(false);}}
 return <div className="search-wrap"><form role="search" onSubmit={submit} className="ticker-search"><label className="sr-only" htmlFor="ticker">Ticker</label><span aria-hidden="true">⌕</span><input id="ticker" name="ticker" type="search" placeholder="Search a ticker, e.g. SPY" maxLength={16} required autoComplete="off"/><Button disabled={busy}>{busy?'Requesting…':'Research ticker'}</Button></form>{error&&<p ref={alert} tabIndex={-1} role="alert">{error}</p>}</div>;
}
