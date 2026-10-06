"""Pinned loopback synthetic browser load. No arbitrary hosts or credentials."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from member_dashboard.launch import read_private_json,validate_staging,private_target


def authenticate_staging(origin,manifest):
    validate_staging(origin,manifest)
    # Pin exact local certificate before sending any HTTP or loading a browser.
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    connection=http.client.HTTPSConnection('localhost',3443,context=context,timeout=3)
    try:
        connection.connect()
        if hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()!=manifest['certificate_sha256']:
            raise ValueError('staging_certificate_mismatch')
        connection.request('GET','/__fixture/identity')
        response=connection.getresponse()
        raw=response.read(65537)
        if response.status!=200 or len(raw)>65536: raise ValueError('staging_identity_unavailable')
        identity=json.loads(raw)
        if identity!={key:manifest[key] for key in ('mode','origin','nonce','certificate_sha256','expires_at')}:
            raise ValueError('staging_identity_mismatch')
    finally: connection.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--members',type=int,default=20)
    parser.add_argument('--duration-seconds',type=int,default=300)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--node',type=Path,required=True)
    args=parser.parse_args()
    if not 2<=args.members<=20 or not 5<=args.duration_seconds<=300: parser.error('bounded synthetic load required')
    manifest=read_private_json(args.manifest)
    private_target(args.manifest.parent,args.output)
    authenticate_staging(args.base_url,manifest)
    if not args.node.is_absolute() or not args.node.is_file(): parser.error('explicit Node runtime required')
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'NEXT_TELEMETRY_DISABLED':'1'}
    result=subprocess.run([str(args.node),str(root/'web/member-dashboard/e2e/load.mjs'),
        str(args.manifest),str(args.output),str(args.members),str(args.duration_seconds)],
        cwd=root/'web/member-dashboard',env=env,timeout=args.duration_seconds+180)
    return result.returncode


if __name__=='__main__': raise SystemExit(main())
