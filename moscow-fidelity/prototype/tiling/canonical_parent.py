"""Read a revision's parent without duplicating its unchanged city records.

Every value is decoded from the parent file. Equal records can share Python
objects with the current city; all existing semantic comparisons still run.
The returned tree and the reference must be treated as read-only by audits.
"""
import gc
import hashlib
import json
import ijson
from ijson.common import ObjectBuilder
from canonical_store import open_canonical, canonical_digest, dump_compact


def same_json(a, b):
    if type(a) is not type(b) or a != b:
        return False
    # Python equality equates True/1 and 1/1.0, including inside dictionaries.
    # Reuse must retain the parent's exact decoded types and object key order.
    if isinstance(a, (dict, list)):
        return json.dumps(a, ensure_ascii=False, separators=(',', ':')) == json.dumps(b, ensure_ascii=False, separators=(',', ':'))
    return True


def value_from_events(events, first):
    event, value = first
    if event not in ('start_map', 'start_array'):
        if event in ('map_key', 'end_map', 'end_array'):
            raise ValueError('Unexpected JSON event')
        return value
    builder = ObjectBuilder()
    builder.event(event, value)
    depth = 1
    while depth:
        event, value = next(events)
        builder.event(event, value)
        depth += (event in ('start_map', 'start_array')) - (event in ('end_map', 'end_array'))
    return builder.value


def exact_parent_candidate(path, current, changed_keys):
    candidate = dict(current)
    missing = object()
    for key in changed_keys:
        # The C parser discards unrelated fields without materializing them.
        with open_canonical(path, 'rb') as stream:
            previous = next(ijson.items(stream, key, use_float=True), missing)
        if previous is missing:
            candidate.pop(key, None)
        else:
            candidate[key] = previous
    digest = hashlib.sha256()
    class Writer:
        def write(self, text):
            digest.update(text.encode('utf-8'))
            return len(text)
    dump_compact(candidate, Writer())
    # No assumption about unchanged fields is trusted. Exact parent bytes must
    # match; older formatting or any unexpected change uses the full reader.
    return candidate if digest.hexdigest() == canonical_digest(path) else None


def load_parent(path, current, *, changed_keys=None):
    """Return the complete parent, reusing only exactly equal decoded values."""
    if changed_keys is not None:
        candidate = exact_parent_candidate(path, current, changed_keys)
        if candidate is not None:
            gc.freeze()
            print('PARENT VERIFIED identical canonical bytes; unchanged arrays shared', flush=True)
            return candidate
    with open_canonical(path, 'rb') as stream:
        events = iter(ijson.basic_parse(stream, use_float=True))
        if next(events) != ('start_map', None):
            raise ValueError('Canonical city must be a JSON object')
        result = {}
        while True:
            event, key = next(events)
            if event == 'end_map':
                break
            if event != 'map_key' or key in result:
                raise ValueError('Invalid or repeated canonical field')
            first = next(events)
            previous = current.get(key)
            if first[0] == 'start_array' and isinstance(previous, list):
                rows = []
                by_id = None
                while True:
                    item = next(events)
                    if item[0] == 'end_array':
                        break
                    row = value_from_events(events, item)
                    index = len(rows)
                    if index < len(previous) and same_json(row, previous[index]):
                        row = previous[index]
                    elif isinstance(row, dict) and isinstance(row.get('id'), str):
                        if by_id is None:
                            by_id = {r['id']: r for r in previous
                                     if isinstance(r, dict) and isinstance(r.get('id'), str)}
                        candidate = by_id.get(row['id'])
                        if same_json(row, candidate):
                            row = candidate
                    rows.append(row)
                result[key] = previous if len(rows) == len(previous) and all(a is b for a, b in zip(rows, previous)) else rows
            else:
                value = value_from_events(events, first)
                result[key] = previous if key in current and same_json(value, previous) else value
        if next(events, None) is not None:
            raise ValueError('Trailing canonical JSON value')
    # The audit holds these acyclic inputs until it returns. Refcount disposal
    # still works, while temporary spatial indexes need not repeatedly scan them.
    gc.freeze()
    return result
