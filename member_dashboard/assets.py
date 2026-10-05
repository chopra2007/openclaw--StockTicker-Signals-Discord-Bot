"""Private PNG assets; parent, current source permissions and owner on every read."""
from io import BytesIO
import json
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from .authorization import require_member
from .auth import AuthError
from .features import require_features
from .publication import evidence_retraction


def validate_png(png):
    if not isinstance(png,bytes) or not 8 <= len(png) <= 2_000_000 or not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Bounded PNG required')
    from PIL import Image
    try:
        with Image.open(BytesIO(png)) as image:
            if image.format != 'PNG' or image.width > 4096 or image.height > 4096 or image.width*image.height > 8_000_000:
                raise ValueError('Chart dimensions exceed bound')
            image.verify()
    except Exception as exc:
        raise ValueError('Invalid chart image') from exc


def store_chart(result_id: str, png: bytes, *, con, asset_id, lineage, now) -> str:
    """Only JobService's authorized transaction calls this trusted insertion."""
    validate_png(png)
    parent=con.execute('SELECT content_json FROM market_results WHERE id=?',(result_id,)).fetchone()
    if parent is None or json.loads(parent[0]).get('payload',{}).get('chart_asset_id') != asset_id:
        raise ValueError('Immutable parent must contain chart identity')
    con.execute('INSERT INTO assets(id,result_id,content_type,content,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
        (asset_id,result_id,'image/png',png,json.dumps([s.model_dump() for s in lineage.sources]),
         json.dumps([d.model_dump() for d in lineage.field_dependencies]),json.dumps(lineage.required_features),lineage.retention_deadline,now))
    return asset_id


class AssetService:
    def __init__(self, jobs): self.jobs=jobs

    def read(self, principal, asset_id, now):
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            try: self.jobs.auth.revalidate(principal,now,con=con)
            except AuthError: return None
            asset=con.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchone()
            if asset is None: return None
            parent=con.execute('SELECT * FROM market_results WHERE id=?',(asset['result_id'],)).fetchone()
            result = self.jobs._read_result(con,parent,now,historical=True) if parent else None
            if result is None or any(evidence_retraction(con,item,self.jobs.policy) is not None for item in result.evidence): return None
            lineage=self.jobs.policy.stored_lineage(asset)
            if lineage is None or not require_features(con,lineage.required_features): return None
            if not all(self.jobs.policy._authorize_lineage(con,lineage,use,now,parent['observed_at']).allowed for use in ('retain','display_raw','display_derived')):
                return None
            # An owned report is sufficient even after its request is discarded.
            owned=con.execute("""SELECT 1 FROM report_owners o JOIN report_versions v ON o.report_id=v.report_id AND o.current_version_id=v.id,
                json_each(CASE WHEN json_valid(v.content_json) THEN v.content_json ELSE '{}' END) item
                WHERE o.member_id=? AND o.deleted_at IS NULL
                AND json_extract(CASE WHEN item.type='object' THEN item.value ELSE '{}' END,'$.result_id')=? LIMIT 1""",
                (principal.member_id,asset['result_id'])).fetchone() is not None
            return bytes(asset['content']) if owned else None


router=APIRouter(prefix='/api/v1/assets')


@router.get('/{asset_id}')
def read_asset(asset_id: str, request: Request, principal=Depends(require_member)):
    png=AssetService(request.app.state.research).read(principal,asset_id,request.app.state.clock())
    if png is None: raise HTTPException(404)
    return Response(png,media_type='image/png',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
