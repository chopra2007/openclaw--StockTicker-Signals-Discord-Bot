"""Current web-only feature guards; administrative mutations live elsewhere."""
import json

SECTIONS = ('analysis', 'sec', 'options', 'em_daily', 'em_weekly')


def feature_mask(con):
    return {row[0]: [bool(row[1]), row[2]] for row in con.execute('SELECT name,enabled,version FROM features')}


def require_features(con, required):
    mask = feature_mask(con)
    return bool(required) and all(name in mask and mask[name][0] for name in required)


def mask_current(con, saved):
    current = feature_mask(con)
    if isinstance(saved, str):
        saved = json.loads(saved)
    return all(current.get(name) == stamp for name, stamp in saved.items())
