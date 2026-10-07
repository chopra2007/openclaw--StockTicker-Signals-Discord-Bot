'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useSession,logout} from './session';
import {TickerSearch} from './ticker-search';
import {ChartIcon,ChatIcon,ClockIcon,StarIcon} from './icons';
export function AppShell({children}:{children:React.ReactNode}){const {member}=useSession();const path=usePathname();if(!member)return null;
 const here=(href:string)=>path===href?'page':undefined;
 const tabs:[string,string,React.ReactNode][]=[['/','Overview',<ChartIcon key="o"/>],...(member.features.assistant.enabled?[['/assistant','Assistant',<ChatIcon key="a"/>] as [string,string,React.ReactNode]]:[]),['/watchlist','Watchlist',<StarIcon key="w"/>],['/history','History',<ClockIcon key="h"/>]];
 return <><a className="skip-link" href="#main">Skip to content</a><header className="app-header"><div className="app-header-inner"><Link href="/" className="brand"><span className="brand-mark" aria-hidden="true"/>Market Edge</Link>
 <nav className="top-nav" aria-label="Main">{tabs.map(([href,label])=><Link key={href} href={href} aria-current={here(href)}>{label}</Link>)}{member.role==='admin'&&<Link href="/admin" aria-current={here('/admin')}>Admin</Link>}</nav>
 <TickerSearch/><details className="member-menu"><summary aria-label={'Account menu: '+member.username}><span className="avatar" aria-hidden="true">{member.username.slice(0,1)}</span><span className="member-name">Account</span><i className="chev" aria-hidden="true"/></summary><div><p>Signed in as {member.username}</p>{member.features.setups.enabled&&<Link className="menu-item" href="/record">Track record</Link>}{member.role==='admin'&&<Link className="menu-item" href="/admin">Admin</Link>}<button type="button" className="menu-item menu-out" onClick={()=>void logout()}>Sign out</button></div></details></div></header>
 {children}
 <nav className="tab-bar" aria-label="Main">{tabs.map(([href,label,icon])=><Link key={href} href={href} aria-current={here(href)}>{icon}{label}</Link>)}</nav></>}
