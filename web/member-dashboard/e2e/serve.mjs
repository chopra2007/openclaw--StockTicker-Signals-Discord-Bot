import {spawn,spawnSync} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import {randomBytes,randomUUID,X509Certificate} from 'node:crypto';
import https from 'node:https';
import http from 'node:http';
import path from 'node:path';
import selfsigned from 'selfsigned';
const root=path.resolve('../..');
const python=process.env.MEMBER_TEST_PYTHON || path.join(root,'.superpowers/sdd/2026-10-05-member-dashboard/web-clean-venv/Scripts/python.exe');
const children=[];
function run(exe,args) { const p=spawn(exe,args,{windowsHide:true,stdio:'inherit',env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',PYTHONPATH:root}}); children.push(p); return p; }
run(process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3444']);
await mkdir('.e2e',{recursive:true});
const cert=await selfsigned.generate([{name:'commonName',value:'localhost'}],{days:1,keySize:2048,extensions:[{name:'subjectAltName',altNames:[{type:2,value:'localhost'}]}]});
await writeFile('.e2e/cert.pem',cert.cert); await writeFile('.e2e/key.pem',cert.private);
if(process.env.MEMBER_LAUNCH==='1') {
  const directory=path.resolve('.e2e','launch-'+randomUUID());
  await mkdir(directory,{mode:0o700});
  if(process.platform==='win32'){
    const secured=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-File',path.join(root,'scripts/member_dashboard_private.ps1'),'-Path',directory,'-Mode','initialize'],{windowsHide:true});
    if(secured.status!==0)throw Error('Private staging directory unavailable');
  }
  const manifest={mode:'synthetic-staging',origin:'https://localhost:3443',nonce:randomBytes(32).toString('hex'),
    certificate_sha256:new X509Certificate(cert.cert).fingerprint256.replaceAll(':','').toLowerCase(),
    expires_at:Date.now()/1000+3500,run_directory:directory};
  await writeFile(path.join(directory,'manifest.json'),JSON.stringify(manifest),{mode:0o600,flag:'wx'});
  await writeFile('.e2e/staging-current.json',JSON.stringify({manifest:path.join(directory,'manifest.json')}));
  run(python,['-m','member_dashboard.runtime','api','--config',path.join(directory,'manifest.json')]);
} else run(python,['e2e/fixture.py']);
const server=https.createServer({key:cert.private,cert:cert.cert},(req,res)=>{
  const api=req.url.startsWith('/api/')||req.url.startsWith('/__fixture/');
  const proxy=http.request({host:'127.0.0.1',port:api?3445:3444,path:req.url,method:req.method,headers:req.headers},up=>{res.writeHead(up.statusCode,up.headers);up.pipe(res);});
  proxy.on('error',()=>{res.writeHead(503);res.end('Starting synthetic fixture');}); req.pipe(proxy);
});
server.listen(3443,'localhost');
function stop(){server.close();for(const p of children)p.kill();setTimeout(()=>process.exit(),300).unref();}
process.on('SIGINT',stop);process.on('SIGTERM',stop);process.on('exit',()=>{for(const p of children)p.kill();});
