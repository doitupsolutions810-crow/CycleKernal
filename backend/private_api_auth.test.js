'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { privateApiGuard, safeEquals, presentedToken } = require('../backend/private_api_auth');

const secret = 'some-long-demo-token-not-a-real-secret';
function run(headers = {}, configured) {
  if (arguments.length < 2) configured = secret;
  let nextCalls = 0, status = null, body = null;
  const res = { status(n) { status = n; return this; }, json(b) { body = b; return this; } };
  const returned = privateApiGuard({ headers }, res, () => { nextCalls++; }, { token: configured });
  return { status, body, nextCalls, returned };
}

test('fail closed when service token is absent or empty', () => {
  for (const bad of [undefined, null, '', '    ', 4]) {
    const out = run({ 'x-admin-token': secret }, bad);
    assert.equal(out.status, 503);
    assert.equal(out.nextCalls, 0);
  }
});

test('reject missing and wrong credentials', () => {
  for (const headers of [{}, { authorization:'Bearer invalid' }, { 'x-admin-token':'invalid' },
      { authorization: 'Bearer ' + secret + ' ' }, { authorization: 'basic x' },
      { 'x-admin-token': secret, authorization: 'Bearer ' + secret },
      { authorization: ['Bearer ' + secret, 'Bearer bad'] },
      { 'x-admin-token': [secret, secret] }]) {
    const out = run(headers);
    assert.equal(out.status, 401);
    assert.equal(out.nextCalls, 0);
  }
});

test('accept exact X-Admin-Token header', () => {
  const out = run({ 'x-admin-token': secret });
  assert.equal(out.nextCalls, 1);assert.equal(out.status,null);
});

test('accept exact Bearer value', () => {
  const out = run({ authorization: 'Bearer ' + secret });
  assert.equal(out.nextCalls, 1);assert.equal(out.status,null);
});

test('never normalize whitespace in presented tokens', () => {
  assert.equal(safeEquals(secret + ' ', secret), false);
  assert.equal(safeEquals(secret, secret), true);
  assert.equal(presentedToken({headers:{authorization:'Bearer ' + secret + ' '}}),null);
});

test('invalid types never throw or authorize', () => {
  for (const val of [0, true, null, {}, ['foo']]) assert.equal(safeEquals(val, secret),false);
});

test('reject extra separators in authorization header', () => {
  for (const auth of ['Bearer  ' + secret, 'Bearer ' + secret + ' extra', 'bearer '+secret, 'Bearer']) {
    assert.equal(run({authorization:auth}).status,401);
  }
});

test('server wires the private API gate before every protected route', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const sourcePath = path.resolve(__dirname, '../backend/server.js');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const gate = source.indexOf("app.use('/api', privateApiGuard);");
  const firstPrivate = Math.min(...[
    source.indexOf("app.post('/api/chat/save'"),
    source.indexOf("app.get('/api/chat/history"),
    source.indexOf("app.post('/api/simulation/snapshot'"),
    source.indexOf("app.get('/api/users/active'")
  ].filter(i => i >= 0));
  assert.ok(gate >= 0, 'private API gate must be registered');
  assert.ok(firstPrivate > gate, 'private API gate must precede all handlers');
});
