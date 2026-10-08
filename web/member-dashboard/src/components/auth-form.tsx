'use client';
import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {api,clearAccess} from '@/lib/api';
import {Button} from './ui/button';
type TokenWindow=Window & {__memberLinkToken?:string};
const subscribe=()=>()=>{};
export function AuthForm({mode}:{mode:'login'|'join'|'reset'}){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[show,setShow]=useState(false);const token=useRef(''),alert=useRef<HTMLParagraphElement>(null);const router=useRouter();
 const hydrated=useSyncExternalStore(subscribe,()=>true,()=>false);
 useEffect(()=>{const w=window as TokenWindow;if(w.__memberLinkToken){token.current=w.__memberLinkToken;delete w.__memberLinkToken;}document.querySelector<HTMLElement>('h1')?.focus();},[]);
 const title=mode==='login'?'Sign in':mode==='join'?'Create your account':'Reset your password';
 async function submit(e:React.FormEvent<HTMLFormElement>){e.preventDefault();if(busy)return;setBusy(true);setError('');const form=new FormData(e.currentTarget);const password=String(form.get('password')||'');const username=String(form.get('username')||'');
  try{if(mode!=='login'&&!token.current)throw new Error('missing link');await api('/auth/'+(mode==='join'?'redeem':mode),{method:'POST',body:JSON.stringify(mode==='login'?{username,password}:mode==='join'?{username,password,token:token.current}:{password,token:token.current})});
   if(mode==='login')router.replace('/');else{token.current='';clearAccess();router.replace('/login');}
  }catch{setError(mode==='login'?'Sign in unsuccessful. Check your details and try again.':'This request could not be completed. Check your link and details.');setTimeout(()=>alert.current?.focus(),0);}finally{setBusy(false);}
 }
 const login=mode==='login';
 const brand=<Link href="/" className="brand auth-brand"><span className="brand-mark" aria-hidden="true"/><span className="brand-name">Market Edge<small>By Akash</small></span></Link>;
 const card=<section className="auth-card"><h1 tabIndex={-1}>{title}</h1>{!login&&<p className="muted">{mode==='join'?'An invitation opens your private workspace.':'Use the reset link you were sent.'}</p>}<form method="post" onSubmit={submit}><fieldset disabled={!hydrated||busy}>
 {mode!=='reset'&&<label>Username<input name="username" autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]{3,32}" autoCapitalize="none" spellCheck={false}/></label>}
 <div className="pw-field"><label>Password<input name="password" type={show?'text':'password'} autoComplete={login?'current-password':'new-password'} required minLength={login?1:5} maxLength={128} aria-describedby={!login?'password-note':undefined}/></label><button type="button" className="pw-toggle" aria-label={show?'Hide password':'Show password'} onClick={()=>setShow(v=>!v)}>{show?'Hide':'Show'}</button></div>
 {!login&&<p id="password-note" className="muted small">Use 5–128 characters. Uppercase letters and numbers are optional. Password managers are supported.</p>}
 {error&&<p role="alert" tabIndex={-1} ref={alert}>{error}</p>}<Button disabled={busy} type="submit">{busy?'Please wait…':login?'Sign in':mode==='join'?'Create account':'Reset password'}</Button>
 </fieldset></form>{!login&&<p className="small muted"><Link href="/login">Already have an account? Sign in</Link></p>}</section>;
 if(!login)return <main className="auth-wrap">{brand}{card}</main>;
 return <main className="auth-split"><section className="auth-hero"><Candles/>{brand}<div className="auth-pitch"><p className="auth-headline">See what the market is talking about.</p><p className="auth-tagline">Trade setups, analyst calls and research on any stock.</p>
  <ul className="auth-chips"><li className="chip-green">Live alerts</li><li className="chip-cyan">Entry, stop and targets</li><li className="chip-yellow">Full ticker reports</li></ul></div></section>
  <div className="auth-side">{card}</div></main>;
}
/** Decorative candlestick backdrop for the sign-in page (fixed shape, not market data). */
const CLOSES=[42,44,43,47,49,48,52,51,55,54,50,46,47,45,41,43,46,50,53,52,56,59,58,62,60,57,61,65,64,68,71,69,73,72,76,79,77,81,84,86];
function Candles(){return <svg className="auth-candles" viewBox="0 0 800 270" preserveAspectRatio="none" aria-hidden="true">{CLOSES.map((c,i)=>{const o=i?CLOSES[i-1]:c-2,up=c>=o,y=(v:number)=>270-(v-36)*5,x=i*20+10;
 return <g key={i} fill={up?'#30d158':'#ff453a'} stroke={up?'#30d158':'#ff453a'}><line x1={x} x2={x} y1={y(Math.max(o,c)+2.5)} y2={y(Math.min(o,c)-2)} strokeWidth="2"/><rect x={x-6} width="12" y={y(Math.max(o,c))} height={Math.max(Math.abs(c-o)*5,3)} rx="2" stroke="none"/></g>;})}</svg>}
