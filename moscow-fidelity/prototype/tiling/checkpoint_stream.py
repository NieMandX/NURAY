"""Bound the serializer's memo for large trusted, local geometry checkpoints.

Each batch is an independent pickle. Cross-batch Python object identity is not
part of a canonical record: relationships use explicit IDs, and geometry,
precision, planes and triangle values are retained without approximation.
Legacy single-pickle checkpoints remain readable.
"""
from collections import defaultdict
from functools import wraps
import gc
import pickle
from geometry_pickle import dump

MAGIC = b'NURAY-CHECKPOINT-2\n'
BATCH_SIZE = 8192


def _without_cycle_scans(function):
    @wraps(function)
    def run(*args, **kwargs):
        # Reference counting still releases each temporary batch. Repeated
        # cyclic-GC scans of the entire live city add minutes per batch on a
        # large checkpoint, although those reachable records cannot be freed.
        enabled = gc.isenabled()
        gc.disable()
        try:
            return function(*args, **kwargs)
        finally:
            if enabled:
                gc.enable()
    return run


def _write_rows(rows, stream, batch_size):
    dump(len(rows), stream)
    for start in range(0, len(rows), batch_size):
        dump(rows[start:start + batch_size], stream)


def _read_rows(stream):
    count = pickle.load(stream)
    if not isinstance(count, int) or count < 0:
        raise ValueError('Invalid checkpoint row count')
    rows = []
    while len(rows) < count:
        batch = pickle.load(stream)
        if not isinstance(batch, list) or not batch or len(rows) + len(batch) > count:
            raise ValueError('Invalid checkpoint row batch')
        rows.extend(batch)
    return rows


@_without_cycle_scans
def save(state, inputs, stream, batch_size=BATCH_SIZE):
    if batch_size < 1:
        raise ValueError('Checkpoint batch size must be positive')
    stream.write(MAGIC)
    dump(list(state), stream)
    for key, value in state.items():
        if isinstance(value, list):
            dump('rows', stream)
            _write_rows(value, stream, batch_size)
        elif key in ('groups', 'shading_flags') and isinstance(value, dict):
            if not all(isinstance(rows, list) for rows in value.values()):
                raise ValueError('Expected canonical triangle/flag lists')
            dump('series-map', stream)
            dump((isinstance(value, defaultdict),
                  value.default_factory if isinstance(value, defaultdict) else None,
                  list(value)), stream)
            for rows in value.values():
                _write_rows(rows, stream, batch_size)
        else:
            dump('object', stream)
            dump(value, stream)
    dump(inputs, stream)


@_without_cycle_scans
def load(stream):
    if stream.read(len(MAGIC)) != MAGIC:
        stream.seek(0)
        return pickle.load(stream)
    keys = pickle.load(stream)
    if not isinstance(keys, list) or len(set(keys)) != len(keys):
        raise ValueError('Invalid checkpoint fields')
    state = {}
    for key in keys:
        kind = pickle.load(stream)
        if kind == 'rows':
            value = _read_rows(stream)
        elif kind == 'series-map':
            is_default, factory, series_keys = pickle.load(stream)
            value = defaultdict(factory) if is_default else {}
            for series_key in series_keys:
                value[series_key] = _read_rows(stream)
        elif kind == 'object':
            value = pickle.load(stream)
        else:
            raise ValueError('Unknown checkpoint field kind')
        state[key] = value
    inputs = pickle.load(stream)
    if stream.read(1):
        raise ValueError('Unexpected trailing checkpoint data')
    return state, inputs
