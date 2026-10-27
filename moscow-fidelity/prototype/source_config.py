"""Resolve one explicit source snapshot, without mixing acquisition dates."""
import json
from pathlib import Path

def plan_path(source):
    source=Path(source)
    if (source/'plan.json').is_file():return source/'plan.json'
    return source/'output/area_10000/plan.json'

def load_plan(source):
    return json.loads(plan_path(source).read_text())

def output_path(source):
    plan=load_plan(source)
    return Path(plan['output']) if plan.get('output') else Path(source)/'output'/f"area_{plan['size_m']}"
