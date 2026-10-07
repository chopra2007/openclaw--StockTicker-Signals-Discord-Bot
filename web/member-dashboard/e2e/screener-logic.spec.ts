import {test,expect} from '@playwright/test';
import {candidates,conditions,defaultScreen,emptyFilters,savedSchema,screenCandidates,sortCandidates,validateFilters} from '../src/lib/screener';
import type {LatestCard} from '../src/lib/contracts';
const card=(ticker:string,observed_at=1000):LatestCard=>({id:ticker,ticker,observed_at,direction:'bullish',text:'Evidence',url:null,score:null,price:999,plan:null});
const rows=candidates([card('ZERO'),card('NULL'),card('HIGH'),card('HIGH',900)],[{symbol:'ZERO',price:0,change_pct:0},{symbol:'HIGH',price:100,change_pct:-2}],4600);

test('combined duplicates retain setup and group evidence, newest source remains explicit',()=>{
 const setup={...card('MU',1000),source:'alert_history',plan:{direction:'long' as const,entry_low:9,entry_high:10,stop:8,targets:[12],computed_at:1000}};
 const group={...card('MU',2000),source:'swarm_alerts',group:{analysts:2,span:'5 min',calls:[{analyst:'author',view:'bearish' as const,reason:'Breakdown'}]}};
 const result=candidates([setup,group],[],3000);
 expect(result).toHaveLength(1);expect(result[0].card.group).toEqual(group.group);expect(result[0].card.plan).toEqual(setup.plan);
 expect(result[0].card.observed_at).toBe(2000);
});
test('inclusive AND filters preserve zero and reject missing quotes, never substitute alert price',()=>{
 expect(rows).toHaveLength(3);
 const result=screenCandidates(rows,{...emptyFilters,minPrice:'0',maxPrice:'100',minChange:'-2',maxChange:'0'},null);
 expect(result.rows.map(r=>r.card.ticker)).toEqual(['ZERO','HIGH']);expect(result.missing).toBe(1);
 expect(screenCandidates(rows,{...emptyFilters,symbols:'null',minPrice:'1'},null).rows).toHaveLength(0);
 expect(screenCandidates(rows,{...emptyFilters,watched:true},new Set(['ZERO'])).rows.map(r=>r.card.ticker)).toEqual(['ZERO']);
 expect(screenCandidates(rows,{...emptyFilters,exclude:'ZERO,HIGH'},null).rows.map(r=>r.card.ticker)).toEqual(['NULL']);
});
test('invalid or contradictory criteria do not become legitimate zero matches',()=>{
 for(const patch of [{minPrice:'Infinity'},{minPrice:'-1'},{minChange:'NaN'},{maxAge:'169'},{minPrice:'10',maxPrice:'1'},{symbols:'SPY',exclude:'spy'},{minChange:'2',maxChange:'-2'}])expect(validateFilters({...emptyFilters,...patch})).not.toBe('');
 expect(validateFilters({...emptyFilters,minPrice:'0',minChange:'-2.5',maxAge:'0'})).toBe('');
 expect(conditions({...emptyFilters,minChange:'-2',maxChange:'0'})[0].required).toBe('−2.00%–0.00%');
});
test('null sort values stay last in both directions, ties are deterministic',()=>{
 expect(sortCandidates(rows,'price',true).map(r=>r.card.ticker)).toEqual(['HIGH','ZERO','NULL']);
 expect(sortCandidates(rows,'price',false).map(r=>r.card.ticker)).toEqual(['ZERO','HIGH','NULL']);
 expect(sortCandidates(rows,'age',false).map(r=>r.card.ticker)).toEqual(['HIGH','NULL','ZERO']);
});
test('persisted preferences reject unknown versions, duplicate columns, invalid shapes',()=>{
 expect(savedSchema.safeParse({version:1,current:defaultScreen,saved:[]}).success).toBe(true);
 for(const current of [{...defaultScreen,columns:['price','price']},{...defaultScreen,sort:'score'}])expect(savedSchema.safeParse({version:1,current,saved:[]}).success).toBe(false);
 expect(savedSchema.safeParse({version:2,current:defaultScreen,saved:[]}).success).toBe(false);
});
