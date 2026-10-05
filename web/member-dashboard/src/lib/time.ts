const formatter=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'});
export function formatPacific(epoch:number|null|undefined){if(epoch==null||!Number.isFinite(epoch))return 'Unavailable';const d=new Date(epoch*1000);return Number.isNaN(d.getTime())?'Unavailable':formatter.format(d);}
// Expiry is a calendar date, never an instant to shift across time zones.
export function formatExpiry(value:string|null){return value&&/^\d{4}-\d{2}-\d{2}$/.test(value)?value:'Unavailable';}
