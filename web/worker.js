'use strict';
// Runs the editor's Python backend (web/web_backend.py) with Pyodide, off the
// page's main thread. World States persist in IndexedDB through IDBFS.

importScripts('pyodide/pyodide.js');

const BUILD = '__BUILD_ID__';
const DATA = '/data';
const STORAGE_LOCK = 'thedas-world-state-storage';
// Other tabs announce saved changes; reload storage before the next request.
const channel = new BroadcastChannel(STORAGE_LOCK);
let stale = true;
channel.onmessage = () => { stale = true; };

function status(message) { postMessage({type: 'status', message}); }

function syncfs(pyodide, populate) {
  return new Promise((resolve, reject) =>
    pyodide.FS.syncfs(populate, error => error ? reject(error) : resolve()));
}

// Serialize storage access across tabs so revision checks see each other's saves.
async function withStorage(pyodide, persist, action) {
  return navigator.locks.request(STORAGE_LOCK, async () => {
    if (stale) { await syncfs(pyodide, true); stale = false; }
    try { return action(); }
    finally {
      if (persist) { await syncfs(pyodide, false); channel.postMessage('changed'); }
    }
  });
}

const ready = (async () => {
  status('Loading the editor runtime…');
  const pyodide = await loadPyodide({indexURL: new URL('pyodide/', self.location).href});
  status('Loading World State data…');
  const archive = await fetch('python.zip?v=' + BUILD);
  if (!archive.ok) throw new Error('The editor files could not be downloaded.');
  pyodide.unpackArchive(await archive.arrayBuffer(), 'zip', {extractDir: '/app'});
  pyodide.FS.mkdirTree(DATA);
  pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, DATA);
  pyodide.runPython("import sys; sys.path[:0] = ['/app/web', '/app/prototype']");
  status('Opening your World States…');
  // Startup can migrate stored layouts, so it persists like a save.
  const editor = await withStorage(pyodide, true,
    () => pyodide.pyimport('web_backend').WebEditor(DATA, '/tmp/exports'));
  return {pyodide, editor};
})();

self.onmessage = async ({data: {id, method, path, contentType, body}}) => {
  let code = 500, text;
  try {
    const {pyodide, editor} = await ready;
    const persist = !editor.read_only(method, path);
    const result = await withStorage(pyodide, persist,
      () => editor.handle(method, path, contentType, body ? new Uint8Array(body) : null));
    [code, text] = result.toJs();
    result.destroy();
  } catch (error) {
    console.error(error);
    text = JSON.stringify({error: 'The editor could not start or complete this action. Reload the page to try again. (' + (error.message || error) + ')'});
  }
  postMessage({type: 'response', id, status: code, text});
};
