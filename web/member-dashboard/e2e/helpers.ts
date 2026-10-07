import {test as base,expect,type Page,type APIRequestContext} from '@playwright/test';
// One synthetic backend is shared by the serial suite. Isolate its auth ledger
// at case boundaries while retaining the real limits throughout each test.
export const test=base.extend<{authBoundary:void}>({authBoundary:[async({request},use)=>{
  // The HTTPS proxy can become ready before its Python child. Read-only probe;
  // GET on the POST-only control route returns 405 when ready, without
  // spending a CSRF challenge. Do not replay writes or hide other failures.
  await expect.poll(async()=>{
    const response=await request.get('/__fixture/control');
    expect([405,503]).toContain(response.status());return response.status();
  }).toBe(405);
  await control(request,{action:'auth_test_boundary'});await use();
},{auto:true}]});
export const password='synthetic password only';
export async function control(request:APIRequestContext,body:object){const r=await request.post('/__fixture/control',{data:body});expect(r.ok()).toBeTruthy();return r.json();}
export async function join(page:Page,request:APIRequestContext){
  const {token}=await control(request,{action:'invite'});const username='member_'+Math.random().toString(36).slice(2,10);
  await page.goto('/join#'+token);await page.getByLabel('Username',{exact:true}).fill(username);
  await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Create account'}).click();
  await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
  await page.getByLabel('Username',{exact:true}).fill(username);await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByRole('heading',{name:'Overview',exact:true})).toBeVisible();
  return username;
}
export async function research(page:Page,ticker='SPY') {await page.getByRole('searchbox',{name:'Search a ticker'}).fill(ticker);await page.getByRole('searchbox',{name:'Search a ticker'}).press('Enter');await expect(page.getByRole('heading',{name:ticker,exact:true,level:1})).toBeVisible();}
