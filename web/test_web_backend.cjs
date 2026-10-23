// Runs the built site's Python backend under Pyodide in Node, as the browser worker does.
// Usage: node web/test_web_backend.cjs [_site]
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {loadPyodide} = require('pyodide');

const site = path.resolve(process.argv[2] || path.join(__dirname, '..', '_site'));
// The same export from desktop CPython, for a byte-for-byte comparison.
const NATIVE_EXPORT = `
import sys, tempfile
from pathlib import Path
sys.path.insert(0, 'prototype')
from gui import EditorApp
with tempfile.TemporaryDirectory() as tmp:
    app = EditorApp(Path(tmp) / 'profiles', Path(tmp) / 'exports')
    preset = app.catalog.default_preset
    mode = next(entry['mode'] for entry in app.bootstrap()['presets'] if entry['id'] == preset)
    profile = app.save(dict(profile_id=None, revision=0, name='A New Beginning', base_preset=preset, mode=mode, choices={}))
    print(app.export(dict(profile_id=profile.profile_id, revision=profile.revision,
                          title='A New Beginning', filename='A New Beginning.fbmod'))['sha256'])
`;

(async () => {
  const pyodide = await loadPyodide({indexURL: path.join(site, 'pyodide') + path.sep});
  pyodide.unpackArchive(new Uint8Array(fs.readFileSync(path.join(site, 'python.zip'))), 'zip', {extractDir: '/app'});
  pyodide.runPython("import sys; sys.path[:0] = ['/app/web', '/app/prototype']");
  const editor = pyodide.pyimport('web_backend').WebEditor('/data', '/tmp/exports');
  const request = (method, url, body, contentType = 'application/json') => {
    const bytes = body === undefined ? null
      : body instanceof Uint8Array ? body : new TextEncoder().encode(JSON.stringify(body));
    const result = editor.handle(method, url, body === undefined ? null : contentType, bytes);
    const [status, text] = result.toJs(); result.destroy();
    return {status, data: JSON.parse(text)};
  };

  const boot = request('GET', '/api/bootstrap');
  assert.equal(boot.status, 200);
  assert.ok(boot.data.choices.length > 100);
  const art = boot.data.categories.map(category => category.art);
  assert.ok(art.every(url => /^(art|interface-art)\//.test(url)), 'artwork URLs are relative to the page');
  assert.ok(art.every(url => fs.existsSync(path.join(site, decodeURIComponent(url)))), 'artwork is in the site');

  const draft = {profile_id: null, revision: 0, name: 'A New Beginning', base_preset: boot.data.default_preset,
    mode: boot.data.presets.find(preset => preset.id === boot.data.default_preset).mode, choices: {}};
  assert.equal(request('POST', '/api/preview', draft).data.can_export, true);
  const saved = request('POST', '/api/save', draft);
  assert.equal(saved.status, 200);
  assert.equal(saved.data.revision, 1);
  const stale = request('POST', '/api/save', {...draft, profile_id: saved.data.profile_id, revision: 0});
  assert.equal(stale.status, 409, 'stale revisions are rejected');
  assert.equal(editor.read_only('POST', '/api/preview'), true);
  assert.equal(editor.read_only('POST', '/api/save'), false);

  const exported = request('POST', '/api/export', {profile_id: saved.data.profile_id, revision: 1,
    title: 'A New Beginning', filename: 'A New Beginning.fbmod'});
  assert.equal(exported.status, 200, JSON.stringify(exported.data));
  assert.equal(exported.data.name, 'A New Beginning.fbmod');
  const mod = Buffer.from(exported.data.files.mod, 'base64');
  assert.equal(crypto.createHash('sha256').update(mod).digest('hex'), exported.data.sha256);
  assert.deepEqual(pyodide.FS.readdir('/tmp/exports').filter(name => !name.startsWith('.')), [],
    'exports are not kept in browser storage');
  assert.equal(request('POST', '/api/export', {profile_id: saved.data.profile_id, revision: 1,
    directory: '/elsewhere'}).status, 400, 'browser exports cannot choose a folder');

  const upload = request('POST', '/api/save-import/preview', new Uint8Array([1, 2, 3]), 'application/octet-stream');
  assert.equal(upload.status, 400, 'invalid saves report an error instead of failing the worker');
  assert.equal(request('POST', '/api/open-world-state-folder', {}).status, 404);

  const native = execFileSync('python3', ['-X', 'utf8', '-c', NATIVE_EXPORT], {cwd: path.join(__dirname, '..')});
  assert.equal(exported.data.sha256, native.toString().trim(), 'browser export matches desktop Python byte for byte');
  console.log('PASS: bootstrap, relative artwork, preview, save, stale revision, FBMOD export identical to desktop Python and invalid save handling under Pyodide');
})().catch(error => { console.error(error); process.exitCode = 1; });
