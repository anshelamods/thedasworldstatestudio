'use strict';
// Browser stand-in for the desktop application's local server. Editor requests
// go to the Python backend running in web/worker.js and come back as Responses.

const backend = (() => {
  const worker = new Worker('worker.js?v=__BUILD_ID__');
  const pending = new Map();
  let nextId = 0, persistenceRequested = false;

  worker.onmessage = ({data}) => {
    if (data.type === 'status') {
      const message = document.querySelector('#loading:not(.failed) p');
      if (message) message.textContent = data.message;
      return;
    }
    const request = pending.get(data.id);
    if (!request) return;
    pending.delete(data.id);
    request.resolve(new Response(data.text, {status: data.status,
      headers: {'Content-Type': 'application/json; charset=utf-8'}}));
  };
  worker.onerror = event => {
    for (const request of pending.values())
      request.reject(new Error(event.message || 'The editor runtime stopped.'));
    pending.clear();
  };

  // Ask the browser not to evict saved World States under storage pressure.
  function requestPersistence() {
    if (persistenceRequested) return;
    persistenceRequested = true;
    navigator.storage?.persist?.().catch(() => {});
  }

  async function request(path, options = {}) {
    const method = options.method || 'GET';
    const headers = new Headers(options.headers);
    let body = null;
    if (options.body !== undefined && options.body !== null)
      body = typeof options.body === 'string' ? new TextEncoder().encode(options.body).buffer
        : await new Response(options.body).arrayBuffer();
    const response = await new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, {resolve, reject});
      worker.postMessage({id, method, path, contentType: headers.get('Content-Type'), body}, body ? [body] : []);
    });
    if (response.ok && method === 'POST' && path === '/api/save') requestPersistence();
    return response;
  }

  return {fetch: request};
})();
