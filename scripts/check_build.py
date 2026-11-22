"""Verify actual Vercel build output, without dumping environments or secrets."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
output=root/'.vercel/output'
python=json.loads((output/'functions/api/index.func/.vc-config.json').read_text())
node=json.loads((output/'functions/api/download.func/.vc-config.json').read_text())
paths=python.get('filePathMap',{})
assert 'worker/runner.py' in paths
assert 'worker/diagnostics.py' in paths
assert 'worker/requirements.lock' in paths
assert 'worker/shortforge/media.py' in paths
assert not any(Path(name).name.startswith('.env') for name in paths)
assert not any(name.startswith(('tests/','scripts/','docs/','worker/modelos/')) for name in paths)
assert not any(name.endswith('.pyc') for name in paths)
assert not any(part in name for name in paths for part in ('_vendor/cv2/','_vendor/faster_whisper/','_vendor/numpy/'))
assert python['runtime']=='python3.14'
assert node['runtime'].startswith('nodejs')
assert not (output/'static/.env.local').exists()
config=json.loads((output/'config.json').read_text())
assert any('sf_route=jobs' in route.get('dest','') for route in config['routes'])
print(json.dumps({'python_runtime':python['runtime'],'node_runtime':node['runtime'],
                  'worker_bundled':True,'env_files_excluded':True,'media_dependencies_in_function':False,'route_manifest':True}))
