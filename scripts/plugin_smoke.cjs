"use strict";
// No network calls: verify discovery and refusal before invoking HTTP.
const assert = require('node:assert/strict');
const plugin = require('../index.cjs');
(async () => {
  for (const mode of ['full', 'discovery', 'tool-discovery']) {
    let tool;
    plugin.register({ registrationMode: mode, registerTool(value) { tool = value; } });
    assert.equal(tool.name, 'caliclaw');
    for (const action of ['start', 'pause', 'cancel']) {
      const result = JSON.parse((await tool.execute('check', { action })).content[0].text);
      assert.equal(result.ok, false);
    }
  }
  console.log('Plugin discovery and hardware-action refusals passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
