"""Fixed offline observations. No service controls, credentials or app startup."""
import argparse
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from member_dashboard.launch import evaluate,private_output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('preflight','verify'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    # The explicitly supplied existing private output directory is the only
    # filesystem observed. This is not evidence about another deployment host.
    disk=shutil.disk_usage(args.output.parent)
    report=evaluate(disk_free_gib=disk.free/(1024**3),disk_free_pct=100*disk.free/disk.total)
    report['mode']=args.mode
    report['scope']='local-output-volume-only'
    report['verification']='incomplete'  # never infer acceptance from preflight
    private_output(args.output.parent,args.output,report)
    return 2


if __name__=='__main__': raise SystemExit(main())
