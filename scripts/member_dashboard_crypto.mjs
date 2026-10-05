// Fixed AES-256-GCM envelope. Key arrives on stdin, never argv/environment.
import {createCipheriv,createDecipheriv,randomBytes} from 'node:crypto';
const mode=process.argv[2];
if(!['seal','open'].includes(mode))throw Error('invalid mode');
const chunks=[];let size=0;
for await(const chunk of process.stdin){size+=chunk.length;if(size>64*1024*1024+4096)throw Error('input too large');chunks.push(chunk);}
const input=Buffer.concat(chunks),key=input.subarray(0,32),data=input.subarray(32);
if(key.length!==32)throw Error('key length');
let output;
if(mode==='seal'){
  const expires=data.subarray(0,8),plaintext=data.subarray(8);
  const deadline=Number(expires.readBigUInt64BE());
  if(deadline<=Date.now()/1000||deadline>Date.now()/1000+30*86400)throw Error('retention bound');
  const nonce=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,nonce);
  cipher.setAAD(Buffer.concat([Buffer.from('MDB1'),expires]));
  const encrypted=Buffer.concat([cipher.update(plaintext),cipher.final()]);
  output=Buffer.concat([Buffer.from('MDB1'),expires,nonce,cipher.getAuthTag(),encrypted]);
}else{
  if(data.length<40||data.subarray(0,4).toString()!=='MDB1')throw Error('invalid envelope');
  const expires=data.subarray(4,12),decipher=createDecipheriv('aes-256-gcm',key,data.subarray(12,24));
  decipher.setAAD(data.subarray(0,12));decipher.setAuthTag(data.subarray(24,40));
  output=Buffer.concat([decipher.update(data.subarray(40)),decipher.final()]);
  if(Number(expires.readBigUInt64BE())<=Date.now()/1000)throw Error('backup expired');
}
process.stdout.write(output);
