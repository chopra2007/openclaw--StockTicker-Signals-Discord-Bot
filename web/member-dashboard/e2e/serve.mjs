import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import https from 'node:https';
import http from 'node:http';
import path from 'node:path';
import selfsigned from 'selfsigned';
const root=path.resolve('../..');
const python=process.env.MEMBER_TEST_PYTHON || path.join(root,'.superpowers/sdd/2026-10-05-member-dashboard/web-clean-venv/Scripts/python.exe');
const children=[];
function run(exe,args) { const p=spawn(exe,args,{windowsHide:true,stdio:'inherit',env:{...process.env,NEXT_TELEMETRY_DISABLED:'1'}}); children.push(p); return p; }
run(python,['e2e/fixture.py']);
run(process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3444']);
await mkdir('.e2e',{recursive:true});
const cert=await selfsigned.generate([{name:'commonName',value:'localhost'}],{days:1,keySize:2048,extensions:[{name:'subjectAltName',altNames:[{type:2,value:'localhost'}]}]});
await writeFile('.e2e/cert.pem',cert.cert); await writeFile('.e2e/key.pem',cert.private);
const server=https.createServer({key:cert.private,cert:cert.cert},(req,res)=>{
  const api=req.url.startsWith('/api/')||req.url.startsWith('/__fixture/');
  const proxy=http.request({host:'127.0.0.1',port:api?3445:3444,path:req.url,method:req.method,headers:req.headers},up=>{res.writeHead(up.statusCode,up.headers);up.pipe(res);});
  proxy.on('error',()=>{res.writeHead(503);res.end('Starting synthetic fixture');}); req.pipe(proxy);
});
server.listen(3443,'localhost');
function stop(){server.close();for(const p of children)p.kill();setTimeout(()=>process.exit(),300).unref();}
process.on('SIGINT',stop);process.on('SIGTERM',stop);process.on('exit',()=>{for(const p of children)p.kill();});
