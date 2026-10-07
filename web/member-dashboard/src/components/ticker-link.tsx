'use client';
import {useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {api,ApiError,primeResearch} from '@/lib/api';
import type {ResearchRequest} from '@/lib/contracts';

/** A ticker link that opens its report in one tap, as a search would. Opening the address
 *  directly (new tab, shared link) never starts a report: the page asks first. */
export function TickerLink({ticker,className,children}:{ticker:string;className?:string;children?:React.ReactNode}){const router=useRouter();const [busy,setBusy]=useState(false),[error,setError]=useState('');
 async function open(e:React.MouseEvent<HTMLAnchorElement>){if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button!==0)return;e.preventDefault();if(busy)return;setBusy(true);setError('');
  try{const next=await api<ResearchRequest>('/research',{method:'POST',body:JSON.stringify({ticker,refresh:false})});primeResearch(next);router.push('/ticker/'+encodeURIComponent(next.ticker)+'?request='+encodeURIComponent(next.id));}
  catch(err){setError(err instanceof ApiError?err.message:'Unable to open the report.');setBusy(false);}}
 return <><Link href={'/ticker/'+encodeURIComponent(ticker)} className={className} onClick={e=>void open(e)} aria-busy={busy||undefined}>{children??ticker}</Link>{error&&<span role="alert" className="link-error">{error}</span>}</>}
