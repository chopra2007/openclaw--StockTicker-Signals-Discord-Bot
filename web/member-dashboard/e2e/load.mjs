// Only the authenticated, certificate-pinned local staging launcher calls this.
import {chromium,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import https from 'node:https';
import tls from 'node:tls';
import path from 'node:path';

const [manifestPath,output,membersText,durationText]=process.argv.slice(2);
const manifest=JSON.parse(await readFile(manifestPath,'utf8'));
const members=Number(membersText),duration=Number(durationText);
const origin='https://localhost:3443';
if(manifest.mode!=='synthetic-staging'||manifest.origin!==origin||manifest.expires_at<=Date.now()/1000||
  path.dirname(output)!==path.dirname(manifestPath)||members<2||members>20||duration<5||duration>300)throw Error('invalid staging run');
const agent=new https.Agent({keepAlive:false,maxSockets:24});
agent.createConnection=(options,callback)=>{
  const socket=tls.connect({...options,rejectUnauthorized:false},()=>{
    if(createHash('sha256').update(socket.getPeerCertificate(true).raw).digest('hex')!==manifest.certificate_sha256){
      socket.destroy();callback(Error('certificate mismatch'));return;
    }
    callback(null,socket);
  });
  socket.once('error',error=>callback(error));
};
function request(url,{method='GET',headers={},body}={}){
  if(new URL(url).origin!==origin)throw Error('unsupported origin');
  return new Promise((resolve,reject)=>{
    const started=performance.now();
    const req=https.request(url,{agent,method,headers,timeout:5000},res=>{
      const chunks=[];let size=0;
      res.on('data',chunk=>{size+=chunk.length;if(size>4*1024*1024)res.destroy(Error('response too large'));else chunks.push(chunk);});
      res.on('error',reject);
      res.on('end',()=>{
        if(res.statusCode>=300&&res.statusCode<400){reject(Error('redirect rejected'));return;}
        resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks),seconds:(performance.now()-started)/1000});
      });
    });
    req.on('timeout',()=>req.destroy(Error('request timeout')));req.on('error',reject);
    req.end(body);
  });
}
const identity=await request(origin+'/__fixture/identity');
const expected=Object.fromEntries(['mode','origin','nonce','certificate_sha256','expires_at'].map(key=>[key,manifest[key]]));
expect(JSON.parse(identity.body)).toEqual(expected);
async function control(body){const r=await request(origin+'/__fixture/control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});expect(r.status).toBe(200);return JSON.parse(r.body);}
const browser=await chromium.launch();
const pages=[],contexts=[],api=[],render=[],publication=[],postPublicationRender=[],completion=[],stats=[],failures=[];
const password='synthetic password only';
let disconnected=false;
try {
  for(let index=0;index<members;index++){
    const context=await browser.newContext({baseURL:origin,ignoreHTTPSErrors:true,serviceWorkers:'block'});
    contexts.push(context);
    await context.route('**/*',async route=>{
      const req=route.request();
      if(disconnected&&index===0&&req.url().includes('/api/v1/feed')){await route.abort('internetdisconnected');return;}
      try{
        const response=await request(req.url(),{method:req.method(),headers:req.headers(),body:req.postDataBuffer()});
        if(req.method()==='GET'&&req.url().includes('/api/v1/'))api.push(response.seconds);
        const headers={};for(const [key,value] of Object.entries(response.headers))if(value!==undefined)headers[key]=Array.isArray(value)?value.join('\n'):value;
        await route.fulfill({status:response.status,headers,body:response.body});
      }catch{failures.push('browser_transport');await route.abort('failed').catch(()=>{});}
    });
    const page=await context.newPage();pages.push(page);
    const username='load_'+index+'_'+Date.now().toString(36);
    const {token}=await control({action:'invite'});
    await page.goto('/join#'+token);
    await page.getByLabel('Username',{exact:true}).fill(username);
    await page.getByLabel('Password',{exact:true}).fill(password);
    await page.getByRole('button',{name:'Create account'}).click();
    await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
    await page.getByLabel('Username',{exact:true}).fill(username);
    await page.getByLabel('Password',{exact:true}).fill(password);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Your market workspace'})).toBeVisible();
  }
  let sampling=false;
  const sampler=setInterval(async()=>{if(sampling)return;sampling=true;try{stats.push(await control({action:'load_stats'}));}catch{failures.push('metrics_unavailable');}finally{sampling=false;}},2000);
  browser.on('disconnected',()=>clearInterval(sampler));
  // Shared requests exercise dedupe; only four actual symbols exist in fixture.
  await Promise.all(pages.map(async(page,index)=>{
    const ticker=index<Math.ceil(members/2)?'SPY':['QQQ','AAPL','MSFT'][index%3];
    const started=performance.now();
    await page.getByRole('searchbox',{name:'Search a ticker'}).fill(ticker);
    await page.getByRole('searchbox',{name:'Search a ticker'}).press('Enter');
    await expect(page.getByTestId('em_weekly-status')).toHaveText('Completed',{timeout:90000});
    completion.push((performance.now()-started)/1000);
    await page.goto('/');
    await expect(page.getByRole('heading',{name:'Your market workspace'})).toBeVisible();
  }));
  const started=performance.now();let cycle=0;
  while(performance.now()-started<duration*1000){
    const sample=await control({action:'load_publish'});
    publication.push(sample.published_at-sample.eligible_at);
    // A bounded disconnection produces a real browser catch-up on next poll.
    disconnected=cycle===1;
    await Promise.all(pages.map(async(page,index)=>{
      if(disconnected&&index===0)return;
      await expect(page.locator('#feed')).toContainText(sample.version,{timeout:30000});
      const painted=await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(Date.now()/1000)))));
      render.push(painted-sample.eligible_at);
      postPublicationRender.push(painted-sample.published_at);
    }));
    if(disconnected){
      disconnected=false;
      await expect(pages[0].locator('#feed')).toContainText(sample.version,{timeout:30000});
    }
    stats.push(await control({action:'load_stats'}));
    cycle++;
    const remaining=duration*1000-(performance.now()-started);
    if(remaining>0)await new Promise(resolve=>setTimeout(resolve,Math.min(15000,remaining)));
  }
  clearInterval(sampler);
  while(sampling)await new Promise(resolve=>setTimeout(resolve,10));
  const compute=stats.map(s=>s.compute).filter(Boolean);
  // A just-admitted submission may transiently await its executor thread. The
  // fixed two-operation admission ceiling bounds that handoff queue at two.
  if(!compute.length||compute.some(s=>s.python_threads>4||s.executor_queue>2||s.max_actual_operations>2)||stats.some(s=>s.queued>100||s.running>1))failures.push('unbounded_or_missing_runtime_measurement');
  const p95=values=>values.length?[...values].sort((a,b)=>a-b)[Math.ceil(values.length*.95)-1]:null;
  const report={scope:'synthetic-browser-only',production_ready:false,members,duration_seconds:duration,measured_feed_duration_seconds:(performance.now()-started)/1000,
    acceptance_size:members===20&&duration===300,active_poll_seconds:15,
    feed_eligibility_to_render_seconds:{count:render.length,p95:p95(render),samples:render},
    publication_to_render_seconds:{count:postPublicationRender.length,p95:p95(postPublicationRender),samples:postPublicationRender},
    eligibility_to_publication_seconds:{count:publication.length,p95:p95(publication),samples:publication},
    api_read_seconds:{count:api.length,p95:p95(api),samples:api},
    research_completion_seconds:completion,queue_samples:stats,
    failures:[...new Set(failures)],bot_latency_regression_pct:null,
    limits:{compute_slots:1,api_threads:4},
    passed:failures.length===0&&p95(render)<=30&&p95(api)<=1};
  await writeFile(output,JSON.stringify(report,null,2),{mode:0o600,flag:'wx'});
  if(!report.passed)process.exitCode=2;
} catch(error) {
  await writeFile(output,JSON.stringify({scope:'synthetic-browser-only',production_ready:false,passed:false,members,duration_seconds:duration,failures:['browser_flow_failed']}),{mode:0o600,flag:'wx'}).catch(()=>{});
  throw error;
} finally {for(const context of contexts)await context.close();await browser.close();agent.destroy();}
