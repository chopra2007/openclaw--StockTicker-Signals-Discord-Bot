/** Price-change text for the market strip, watchlist, track record and Overview cards. */
export const signed=(v:number,digits=2)=>{const text=Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});return (Number(Math.abs(v).toFixed(digits))===0?'':v>0?'+':'−')+text;};
export const pctText=(v:number|null|undefined,digits=2)=>v==null?'—':signed(v,digits)+'%';
export const tone=(v:number|null|undefined,digits=2)=>v==null||Number(Math.abs(v).toFixed(digits))===0?'':v>0?'up':'down';
export const level=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const clock=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',hour:'numeric',minute:'2-digit'});
/** "1:00 PM" (Pacific). */
export const clockTime=(epoch:number)=>clock.format(new Date(epoch*1000));
/** Distance from the current price to a level, as a signed percent ("+3.2%"). */
export const away=(levelPrice:number|null|undefined,price:number|null|undefined)=>levelPrice==null||!price?null:(levelPrice/price-1)*100;
