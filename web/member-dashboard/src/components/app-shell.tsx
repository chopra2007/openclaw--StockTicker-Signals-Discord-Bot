'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect,useRef} from 'react';
import {useSession,logout} from './session';
import {TickerSearch} from './ticker-search';
import {ChartIcon,ChatIcon,ClockIcon,FilterIcon,StarIcon} from './icons';
export function AppShell({children}:{children:React.ReactNode}){const {member}=useSession();const path=usePathname();const menu=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{const close=(event:PointerEvent)=>{if(event.target instanceof Node&&!menu.current?.contains(event.target))menu.current?.removeAttribute('open');};const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&menu.current?.open){menu.current.open=false;menu.current.querySelector<HTMLElement>('summary')?.focus();}};document.addEventListener('pointerdown',close);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',escape);};},[]);
 useEffect(()=>{menu.current?.removeAttribute('open');},[path]);if(!member)return null;
 const here=(href:string)=>path===href?'page':undefined;
 const tabs:[string,string,React.ReactNode][]=[['/','Overview',<ChartIcon key="o"/>],...((member.features.feed.enabled||member.features.setups.enabled)?[['/screener','Screener',<FilterIcon key="s"/>] as [string,string,React.ReactNode]]:[]),...(member.features.assistant.enabled?[['/assistant','Assistant',<ChatIcon key="a"/>] as [string,string,React.ReactNode]]:[]),['/watchlist','Watchlist',<StarIcon key="w"/>],['/history','History',<ClockIcon key="h"/>]];
 return <><a className="skip-link" href="#main">Skip to content</a><header className="app-header"><div className="app-header-inner"><Link href="/" className="brand"><span className="brand-mark" aria-hidden="true"/>Market Edge</Link>
 <nav className="top-nav" aria-label="Main">{tabs.map(([href,label,icon])=><Link key={href} href={href} aria-current={here(href)}>{icon}{label}</Link>)}{member.role==='admin'&&<Link href="/admin" aria-current={here('/admin')}>Admin</Link>}</nav>
 <TickerSearch/><details ref={menu} className="member-menu"><summary aria-label={'Account menu: '+member.username}><span className="avatar" aria-hidden="true">{member.username.slice(0,1)}</span><span className="member-name">Account</span><i className="chev" aria-hidden="true"/></summary><div><p>Signed in as {member.username}</p>{member.features.setups.enabled&&<Link className="menu-item" href="/record">Track record</Link>}{member.role==='admin'&&<Link className="menu-item" href="/admin">Admin</Link>}<button type="button" className="menu-item menu-out" onClick={()=>void logout()}>Sign out</button></div></details></div></header>
 {children}
 <nav className="tab-bar" aria-label="Main">{tabs.map(([href,label,icon])=><Link key={href} href={href} aria-current={here(href)}>{icon}{label}</Link>)}</nav></>}
