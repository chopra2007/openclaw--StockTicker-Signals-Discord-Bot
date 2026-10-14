import {expect} from '@playwright/test';
import {test,join} from './helpers';

test('retired track record has no Home card, account link or background request',async({page,request})=>{
 const recordRequests:string[]=[];
 page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/v1/record'))recordRequests.push(r.url());});
 await join(page,request);
 await expect(page.getByRole('heading',{name:'Watchlist',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Track record',exact:true})).toHaveCount(0);
 await page.locator('.member-menu summary').click();
 await expect(page.getByRole('link',{name:/Track record/})).toHaveCount(0);
 expect(recordRequests).toEqual([]);
});

test('retired track record bookmarks return to Overview without fetching outcomes',async({page,request})=>{
 await join(page,request);
 const recordRequests:string[]=[];
 page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/v1/record'))recordRequests.push(r.url());});
 await page.goto('/record');
 await expect(page).toHaveURL('https://localhost:3443/');
 await expect(page.getByRole('heading',{name:'Overview',exact:true})).toBeVisible();
 expect(recordRequests).toEqual([]);
});
