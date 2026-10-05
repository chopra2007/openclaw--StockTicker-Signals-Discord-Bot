import {expect,type Page,type APIRequestContext} from '@playwright/test';
export const password='synthetic password only';
export async function control(request:APIRequestContext,body:object){const r=await request.post('/__fixture/control',{data:body});expect(r.ok()).toBeTruthy();return r.json();}
export async function join(page:Page,request:APIRequestContext){
  const {token}=await control(request,{action:'invite'});const username='member_'+Math.random().toString(36).slice(2,10);
  await page.goto('/join#'+token);await page.getByLabel('Username',{exact:true}).fill(username);
  await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Create account'}).click();
  await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
  await page.getByLabel('Username',{exact:true}).fill(username);await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByRole('heading',{name:'Your market workspace'})).toBeVisible();
  return username;
}
export async function research(page:Page,ticker='SPY') {await page.getByRole('searchbox',{name:'Ticker'}).fill(ticker);await page.getByRole('button',{name:'Research ticker'}).click();await expect(page.getByRole('heading',{name:`${ticker} research`,exact:true})).toBeVisible();}
