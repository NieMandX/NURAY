"""Read the current canonical verdict without a giant Node JSON string."""
import json
from pathlib import Path
import sys
import ijson


def validation_passed(path):
    passed=None
    with Path(path).open('rb') as stream:
        # Exhaust the parser: malformed/trailing data after `passed` must not
        # be silently accepted. The last duplicate key matches JSON.parse.
        try:
            for value in ijson.items(stream,'passed',use_float=True):
                passed=value
        except ijson.JSONError as error:
            raise ValueError('Invalid canonical validation report') from error
    return passed is True


if __name__=='__main__':
    if not validation_passed(sys.argv[1]):
        raise ValueError('Canonical validation failed')
    print(json.dumps({'passed':True}))
