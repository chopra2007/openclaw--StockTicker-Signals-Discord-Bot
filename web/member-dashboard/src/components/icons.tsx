/** Small line icons in the iOS style (stroke follows text colour). */
const base={width:22,height:22,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.8,strokeLinecap:'round' as const,strokeLinejoin:'round' as const,'aria-hidden':true};
export const ChartIcon=()=><svg {...base}><path d="M4 19h16M6 15l4-5 3 3 5-7"/></svg>;
export const ChatIcon=()=><svg {...base}><path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4A8 8 0 1 1 20 12z"/></svg>;
export const ClockIcon=()=><svg {...base}><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>;
export const SearchIcon=()=><svg {...base} width={17} height={17}><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>;
export const SendIcon=()=><svg {...base} width={18} height={18} strokeWidth={2.4}><path d="M12 19V5M6 11l6-6 6 6"/></svg>;
export const StarIcon=()=><svg {...base}><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9l-5.2 2.8 1-5.9-4.3-4.1 5.9-.8z"/></svg>;
