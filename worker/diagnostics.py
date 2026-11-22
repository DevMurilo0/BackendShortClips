"""Optional operator diagnostics with a fixed schema; no logs from dependencies."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


def record(phase, *, seconds=None, byte_count=None, error=None, exit_code=None):
    path = os.getenv('SHORTFORGE_DIAGNOSTICS_PATH')
    if not path: return
    if not re.fullmatch(r'[a-z_]{1,60}', phase): raise ValueError('Invalid diagnostic phase')
    data = {'at': datetime.now(timezone.utc).isoformat(), 'phase': phase}
    if seconds is not None: data['seconds'] = round(seconds, 2)
    if byte_count is not None: data['bytes'] = int(byte_count)
    if error is not None: data['error_type'] = type(error).__name__
    if exit_code is not None: data['exit_code'] = int(exit_code)
    with Path(path).open('a') as file: file.write(json.dumps(data) + '\n')
