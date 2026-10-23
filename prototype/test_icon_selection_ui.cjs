// A canceled/reset asynchronous icon read cannot change a later settings view.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const elements = new Map(), decodes = [];
const $ = id => {
  if (!elements.has(id)) elements.set(id, {events: {}, value: '', disabled: false,
    addEventListener(name, fn) { this.events[name] = fn; },
    close() { this.events.close?.(); }, click() {}});
  return elements.get(id);
};
const state = {fbmodIcon: 'stored-icon', iconLoading: false};
const context = vm.createContext({$, state, renderFbmodIcon() {},
  FileReader: class { readAsDataURL() { this.result = 'data:image/png;base64,pending'; this.onload(); } },
  Image: class { naturalWidth = 2; naturalHeight = 2; decode() { return new Promise(resolve => decodes.push(resolve)); } }});
const helper = source.indexOf('function cancelIconRead(');
if (helper >= 0) vm.runInContext(source.slice(helper, source.indexOf("$('choose-fbmod-icon').onclick")), context);
vm.runInContext(source.slice(source.indexOf("$('choose-fbmod-icon').onclick"), source.indexOf("$('fbmod-settings-form').onsubmit")), context);
(async () => {
  for (const action of ['close', 'reset']) {
    state.fbmodIcon = 'stored-icon';
    const pending = $('fbmod-icon-file').onchange({target: {files: [{size: 64, type: 'image/png'}], value: 'icon.png'}});
    await Promise.resolve();
    assert.equal(decodes.length, 1);
    if (action === 'close') {
      $('fbmod-settings-dialog').close();
      state.fbmodIcon = 'reopened-stored-icon';
    } else $('reset-fbmod-icon').onclick();
    decodes.shift()(); await pending;
    assert.equal(state.fbmodIcon, action === 'close' ? 'reopened-stored-icon' : null,
      'A superseded image decode must not replace the later icon selection');
    assert.equal(state.iconLoading, false);
    assert.equal($('save-fbmod-settings').disabled, false);
  }
  console.log('PASS: closing/reopening or resetting icon settings invalidates pending image reads');
})().catch(error => { console.error(error); process.exitCode = 1; });
