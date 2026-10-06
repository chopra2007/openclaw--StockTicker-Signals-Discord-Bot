'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useSession,logout} from './session';
import {TickerSearch} from './ticker-search';
import {Button} from './ui/button';
export function AppShell({children}:{children:React.ReactNode}){const {member}=useSession();const path=usePathname();if(!member)return null;
 const link=(href:string,label:string)=><Link href={href} aria-current={path===href?'page':undefined}>{label}</Link>;
 return <><a className="skip-link" href="#main">Skip to content</a><header className="app-header"><div className="app-header-inner"><Link href="/" className="brand"><span className="brand-mark" aria-hidden="true"/>Fieldnote</Link>
 <nav className="top-nav" aria-label="Workspace">{link('/','Overview')}{link('/history','History')}{member.features.assistant.enabled&&link('/assistant','Assistant')}{member.role==='admin'&&link('/admin','Admin')}</nav>
 <TickerSearch/><details className="member-menu"><summary aria-label="Member menu">{member.username}</summary><div><Button variant="outline" onClick={()=>void logout()}>Sign out</Button></div></details></div></header>{children}</>}
