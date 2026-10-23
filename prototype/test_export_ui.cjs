// Completed exports download the FBMOD and offer the report; failures keep the dialog open.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {value: 'Test', hidden: true, open: true,
    close() { this.open = false; }});
  return elements.get(id);
};
const state = {draft: {profile_id: 'saved', revision: 2}, preview: {can_export: true}, showDiagnostics: false};
const messages = [], downloads = [], requests = [];
const result = {name: 'Test.fbmod', report_name: 'Test.report.json', revision: 2, sha256: 'abc',
  files: {mod: Buffer.from('FBMOD').toString('base64'), report: Buffer.from('{}').toString('base64')},
  warnings: ['The FBMOD was saved, but the export folder could not be remembered.']};
let fail = false;
const context = vm.createContext({$, state, Blob, Uint8Array, atob, save: async () => true,
  api: async (path, data) => { requests.push([path, data]); if (fail) throw Error('Out of memory'); return result; },
  downloadBlob: (blob, name) => downloads.push([blob, name]),
  busy: value => { state.busy = value; }, toast: (...args) => messages.push(args)});
vm.runInContext(source.slice(source.indexOf('async function exportMod('),
  source.indexOf('function renderFbmodIcon(')), context);
(async () => {
  await context.exportMod();
  assert.equal(requests[0][0], '/api/export');
  assert.deepEqual(Object.keys(requests[0][1]).sort(), ['filename', 'profile_id', 'revision', 'title']);
  assert.equal(downloads.length, 1);
  assert.equal(downloads[0][1], 'Test.fbmod');
  assert.equal(await downloads[0][0].text(), 'FBMOD');
  assert.equal(messages.length, 1);
  assert.equal(messages[0][0], 'FBMOD downloaded · Revision 2');
  assert.match(messages[0][1], /could not be remembered/);
  assert.equal(messages[0][2], false, 'a warning must not mark a completed export as failed');
  assert.equal(messages[0][3][0].label, 'Download report');
  messages[0][3][0].run();
  assert.equal(downloads[1][1], 'Test.report.json');
  assert.equal(await downloads[1][0].text(), '{}');
  assert.equal($('fbmod-export-dialog').open, false);
  assert.equal(state.busy, false);
  delete result.warnings;
  await context.exportMod();
  assert.equal(messages[1][1], result.name, 'responses without warnings show only the file name');
  fail = true; $('fbmod-export-dialog').open = true;
  await context.exportMod();
  assert.equal(messages.length, 2, 'failed exports must not show a success toast');
  assert.equal(downloads.length, 3, 'failed exports must not download a file');
  assert.equal($('fbmod-export-dialog').open, true);
  assert.equal($('fbmod-export-error').hidden, false);
  assert.equal($('fbmod-export-error').textContent, 'Out of memory');
  assert.equal(state.busy, false);
  console.log('PASS: FBMOD download, report action, export warnings and genuine export failure');
})().catch(error => { console.error(error); process.exitCode = 1; });
