"""Existing browser fixture, using the shared synthetic-only composition."""
from pathlib import Path
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from member_dashboard.synthetic import create_synthetic
import uvicorn
RUN=Path(__file__).resolve().parents[1]/'.e2e'/str(uuid4())
app=create_synthetic(RUN)
if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=3445,access_log=False,log_level='warning')
