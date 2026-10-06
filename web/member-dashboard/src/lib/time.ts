const formatter=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'});
export function formatPacific(epoch:number|null|undefined){if(epoch==null||!Number.isFinite(epoch))return 'Unavailable';const d=new Date(epoch*1000);return Number.isNaN(d.getTime())?'Unavailable':formatter.format(d);}
// Expiry is a calendar date, never an instant to shift across time zones.
export function formatExpiry(value:string|null){return value&&/^\d{4}-\d{2}-\d{2}$/.test(value)?value:'Unavailable';}
const short=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const dateOnly=new Intl.DateTimeFormat('en-US',{timeZone:'UTC',month:'short',day:'numeric'});
/** "Oct 6, 1:23 PM" (Pacific). */
export function formatShort(epoch:number|null|undefined){if(epoch==null||!Number.isFinite(epoch))return '';return short.format(new Date(epoch*1000));}
/** "Oct 9" for an option expiry date. */
export function formatDay(value:string|null){return value&&/^\d{4}-\d{2}-\d{2}$/.test(value)?dateOnly.format(new Date(value+'T00:00:00Z')):'';}
