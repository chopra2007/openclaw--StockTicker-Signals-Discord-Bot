'use client';
import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {api,clearAccess} from '@/lib/api';
import {Button} from './ui/button';
type TokenWindow=Window & {__memberLinkToken?:string};
const subscribe=()=>()=>{};
export function AuthForm({mode}:{mode:'login'|'join'|'reset'}){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);const token=useRef(''),alert=useRef<HTMLParagraphElement>(null);const router=useRouter();
 const hydrated=useSyncExternalStore(subscribe,()=>true,()=>false);
 useEffect(()=>{const w=window as TokenWindow;if(w.__memberLinkToken){token.current=w.__memberLinkToken;delete w.__memberLinkToken;}document.querySelector<HTMLElement>('h1')?.focus();},[]);
 const title=mode==='login'?'Sign in':mode==='join'?'Create your account':'Reset your password';
 async function submit(e:React.FormEvent<HTMLFormElement>){e.preventDefault();if(busy)return;setBusy(true);setError('');const form=new FormData(e.currentTarget);const password=String(form.get('password')||'');const username=String(form.get('username')||'');
  try{if(mode!=='login'&&!token.current)throw new Error('missing link');await api('/auth/'+(mode==='join'?'redeem':mode),{method:'POST',body:JSON.stringify(mode==='login'?{username,password}:mode==='join'?{username,password,token:token.current}:{password,token:token.current})});
   if(mode==='login')router.replace('/');else{token.current='';clearAccess();router.replace('/login');}
  }catch{setError(mode==='login'?'Sign in unsuccessful. Check your details and try again.':'This request could not be completed. Check your link and details.');setTimeout(()=>alert.current?.focus(),0);}finally{setBusy(false);}
 }
 return <main className="auth-wrap"><Link href="/" className="brand"><span className="brand-mark" aria-hidden="true"/>Market Edge</Link><section className="auth-card"><h1 tabIndex={-1}>{title}</h1><p className="muted">{mode==='join'?'An invitation opens your private workspace.':mode==='reset'?'Use the reset link supplied by your administrator.':'Trade setups, analyst calls and research on any stock.'}</p><form method="post" onSubmit={submit}><fieldset disabled={!hydrated||busy}>
 {mode!=='reset'&&<label>Username<input name="username" autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]{3,32}" autoCapitalize="none" spellCheck={false}/></label>}
 <label>Password<input name="password" type="password" autoComplete={mode==='login'?'current-password':'new-password'} required minLength={mode==='login'?1:15} maxLength={128} aria-describedby={mode!=='login'?'password-note':undefined}/></label>
 {mode!=='login'&&<p id="password-note" className="muted small">Use 15–128 characters. Password managers are supported.</p>}
 {error&&<p role="alert" tabIndex={-1} ref={alert}>{error}</p>}<Button disabled={busy} type="submit">{busy?'Please wait…':mode==='login'?'Sign in':mode==='join'?'Create account':'Reset password'}</Button>
 </fieldset></form><p className="small muted">{mode==='login'?'Invitation or reset link needed? Contact your administrator.':<Link href="/login">Already have an account? Sign in</Link>}</p></section></main>;
}
