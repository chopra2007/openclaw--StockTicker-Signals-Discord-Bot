"""Explicit local archive/closed-restore operation; never service activation."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from member_dashboard.backup import encrypted_backup,encrypted_restore

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('backup','restore-closed'))
    for field in ('source','output','quota-path','key-file','node'):
        p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--denial-journal',type=Path)
    p.add_argument('--authority-anchor',type=Path)
    args=p.parse_args()
    operation=encrypted_backup if args.mode=='backup' else encrypted_restore
    extra={}
    if args.mode=='restore-closed':
        if args.denial_journal is None or args.authority_anchor is None: p.error('current denial journal and anchor required for restore')
        from member_dashboard.authority import DenialJournal
        extra['denial_journal']=DenialJournal(args.denial_journal,args.authority_anchor)
    operation(args.source,args.output,args.output.parent,quota_path=args.quota_path,key_path=args.key_file,node=args.node,**extra)

if __name__=='__main__': main()
