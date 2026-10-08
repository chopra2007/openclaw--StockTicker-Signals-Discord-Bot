import './globals.css';
import {IBM_Plex_Mono,Inter} from 'next/font/google';
const inter=Inter({subsets:['latin'],variable:'--font-inter',display:'swap'});
const mono=IBM_Plex_Mono({subsets:['latin'],weight:['400','500','600'],variable:'--font-plex-mono',display:'swap'});
import {SessionProvider} from '@/components/session';
export const metadata={title:'Market Edge',description:'Private member research workspace',referrer:'no-referrer'};
export const dynamic = 'force-dynamic';
const stripFragment="if(['/join','/reset'].includes(location.pathname)){window.__memberLinkToken=location.hash.slice(1,129);history.replaceState(null,'',location.pathname);}else if(location.hash&&location.pathname==='/login'){history.replaceState(null,'',location.pathname);}";
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="en" className={inter.variable+' '+mono.variable}><head><script dangerouslySetInnerHTML={{__html:stripFragment}}/></head><body><SessionProvider>{children}</SessionProvider></body></html>}
