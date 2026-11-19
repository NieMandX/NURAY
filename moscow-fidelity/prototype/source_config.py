"""Resolve one explicit source snapshot, without mixing acquisition dates."""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMER_PROJECT_ROOT = PROJECT_ROOT.parents[1] / PROJECT_ROOT.name
RECORDED_ROOTS = (
    ('ChatGPT', 'IDEAS', 'NURAY', PROJECT_ROOT.name),
    ('ChatGPT', 'IDEAS', PROJECT_ROOT.name),
)


def project_path(recorded):
    """Resolve paths in the original and consolidated capture receipts."""
    path = Path(recorded)
    if not path.is_absolute() or path.is_relative_to(PROJECT_ROOT):
        return path
    if path.is_relative_to(FORMER_PROJECT_ROOT):
        return PROJECT_ROOT / path.relative_to(FORMER_PROJECT_ROOT)
    for ancestor in (path, *path.parents):
        if any(ancestor.parts[-len(root):] == root for root in RECORDED_ROOTS):
            return PROJECT_ROOT / path.relative_to(ancestor)
    return path


def plan_path(source):
    source=Path(source)
    if (source/'plan.json').is_file():return source/'plan.json'
    return source/'output/area_10000/plan.json'

def load_plan(source):
    return json.loads(plan_path(source).read_text())

def output_path(source):
    plan=load_plan(source)
    return project_path(plan['output']) if plan.get('output') else Path(source)/'output'/f"area_{plan['size_m']}"
