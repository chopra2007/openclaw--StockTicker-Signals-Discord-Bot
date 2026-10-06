import './globals.css';
import {Inter} from 'next/font/google';
const inter=Inter({subsets:['latin'],variable:'--font-inter',display:'swap'});
import {SessionProvider} from '@/components/session';
export const metadata={title:'Fieldnote',description:'Private member research workspace',referrer:'no-referrer'};
export const dynamic = 'force-dynamic';
const stripFragment="if(['/join','/reset'].includes(location.pathname)){window.__memberLinkToken=location.hash.slice(1,129);history.replaceState(null,'',location.pathname);}else if(location.hash&&location.pathname==='/login'){history.replaceState(null,'',location.pathname);}";
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="en" className={inter.variable}><head><script dangerouslySetInnerHTML={{__html:stripFragment}}/></head><body><SessionProvider>{children}</SessionProvider></body></html>}
