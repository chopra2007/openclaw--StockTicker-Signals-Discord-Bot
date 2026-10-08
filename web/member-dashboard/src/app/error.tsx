'use client';
import {OfflineScreen} from '@/components/status-screen';
/** A page crashed while loading: same look as the "couldn't reach" screen, retry re-renders the page. */
export default function Error({reset}:{error:Error;reset:()=>void}){return <OfflineScreen title="This page didn’t load" message="Something went wrong while loading this page. Nothing is lost." onRetry={reset} signIn={false}/>}
