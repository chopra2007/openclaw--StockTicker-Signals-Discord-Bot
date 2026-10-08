import Link from 'next/link';

/** Full-page message (404, can't reach the server, crashed page) under a plain brand bar. */
export function StatusScreen({children,card}:{children:React.ReactNode;card?:boolean}){
 return <div className="status-page"><header className="status-bar"><Link href="/" className="brand"><span className="brand-mark" aria-hidden="true"/>Market Edge</Link></header>
  <main id="main" className="status-main"><div className={card?'status-card':'status-plain'}>{children}</div></main></div>}

export function NotFoundScreen(){return <StatusScreen>
 <svg className="status-line" viewBox="0 0 320 96" width="320" height="96" aria-hidden="true"><path d="M0 70 30 62 52 66 78 48 100 54 124 36 146 42 168 30" fill="none" stroke="var(--brand)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/><path d="M168 30H320" stroke="#3a3a3c" strokeWidth="3" strokeLinecap="round" strokeDasharray="2 9"/><circle cx="168" cy="30" r="6" fill="#000" stroke="var(--brand)" strokeWidth="3"/></svg>
 <p className="status-code">Error 404</p><h1 tabIndex={-1}>This page doesn’t exist</h1><p className="status-text">The link may be old or mistyped.</p>
 <Link href="/" className="button button-primary status-action">Go to Overview</Link>
</StatusScreen>}

/** The server could not be reached. The session check keeps retrying every 15 seconds on its own. */
export function OfflineScreen({title,message,onRetry,signIn=true}:{title:string;message:string;onRetry:()=>void;signIn?:boolean}){return <StatusScreen card>
 <span className="status-icon" aria-hidden="true"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 8.8a15 15 0 0 1 4.2-2.6M10.7 5.1A15 15 0 0 1 22 8.8M5 12.6a10 10 0 0 1 5.2-2.5M16.8 11.3a10 10 0 0 1 2.2 1.3M8.5 16.4a5 5 0 0 1 7 0M12 20h.01M2 2l20 20"/></svg></span>
 <h1 tabIndex={-1}>{title}</h1><p role="alert" className="status-text">{message}</p>
 {signIn&&<p className="status-pill"><span aria-hidden="true"/>Retrying automatically</p>}
 <button type="button" className="button button-primary status-action status-wide" onClick={onRetry}>Try again</button>
 {signIn&&<Link href="/login" className="status-link">Sign in again</Link>}
</StatusScreen>}

/** Grey outline of the Overview while the session is checked. */
export function LoadingScreen(){return <div className="status-page" aria-busy="true">
 <header className="status-bar"><span className="brand"><span className="brand-mark" aria-hidden="true"/>Market Edge</span><span className="sk sk-nav"/><span className="sk sk-search"/></header>
 <main className="loading-main"><span className="sk sk-title"/><div className="sk-tiles">{[0,1,2,3,4].map(i=><span key={i} className="sk"/>)}</div>
  <div className="sk-cols"><div>{[0,1,2,3].map(i=><span key={i} className="sk"/>)}</div><span className="sk sk-rail"/></div>
  <p role="status" className="loading-pill"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--brand)" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>Checking your session…</p></main></div>}
