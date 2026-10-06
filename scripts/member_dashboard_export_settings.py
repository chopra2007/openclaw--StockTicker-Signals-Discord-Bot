#!/usr/bin/env python3
"""Export the bot's !all calculation settings for the member dashboard's analysis section.

Run with the BOT's Python (it has PyYAML; reads config/consensus.yaml); the dashboard compute child
cannot read bot config. Writes only calculation sections and the technical filter
thresholds; any value still holding an unresolved "$VAR" reference is dropped.
Usage: python3 scripts/member_dashboard_export_settings.py OUTPUT.json
"""
import json
import os
import sys

import yaml

# Raw YAML on purpose: the bot's config loader substitutes real secret values for $VAR refs.
CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'consensus.yaml')

SECTIONS = ('scoring', 'precision_engine', 'all_command', 'features', 'options_flow', 'youtube')


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items() if not (isinstance(v, str) and v.startswith('$'))}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def main(path):
    with open(CONFIG) as source:
        raw = yaml.safe_load(source) or {}
    exported = {'calculation': {name: clean(raw.get(name) or {}) for name in SECTIONS},
                'technical_filters': clean((raw.get('technical') or {}).get('filters') or {})}
    temporary = path + '.pending'
    with open(temporary, 'w') as out:
        json.dump(exported, out, sort_keys=True)
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)
    print(f'analysis settings exported: {len(json.dumps(exported))} bytes')


if __name__ == '__main__':
    main(sys.argv[1])
