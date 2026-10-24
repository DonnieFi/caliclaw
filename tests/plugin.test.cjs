'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const plugin = require('../index.cjs');

test('registers under runtime discovery and calls the workbench without hardware controls', async () => {
  const requests = [];
  const server = http.createServer((req, res) => {
    requests.push([req.method, req.url]);
    res.setHeader('Content-Type', 'application/json');
    res.statusCode = req.url === '/api/slice' ? 409 : 200;
    res.end(JSON.stringify({ simulated: true }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    let tool;
    plugin.register({ registrationMode: 'discovery',
      pluginConfig: { baseUrl: `http://127.0.0.1:${server.address().port}` },
      registerTool(value) { tool = value; } });
    assert.equal(tool.name, 'caliclaw');
    const result = await tool.execute('1', { action: 'status' });
    assert.equal(result.isError, false);
    assert.equal(result.details.data.simulated, true);
    assert.equal((await tool.execute('2', { action: 'slice' })).isError, true);
    assert.equal((await tool.execute('3', { action: 'start' })).isError, true);
    assert.deepEqual(requests, [['GET', '/api/printer'], ['POST', '/api/slice']]);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
