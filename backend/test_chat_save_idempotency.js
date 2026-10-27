'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  canonicalJson,
  chatPayloadDigest,
  createIdempotentChatSaveHandler,
} = require('./chat_save_idempotency');

function responseRecorder() {
  return {
    statusCode: 200,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(body) { this.body = body; return this; },
  };
}

function createFixture({ redisFailure = false, metricsFailure = false, ensureReadyFailure = false } = {}) {
  const rows = new Map();
  let nextId = 1;
  let readyCalls = 0;
  let findAndUpdateCalls = 0;
  let failBeforeUpsert = false;
  let failAfterUpsert = false;
  const logs = [];
  const model = {
    collection: {},
    findOne(filter) {
      return {
        lean: async () => rows.get(filter.operationId) || null,
      };
    },
    findOneAndUpdate(filter, update, options) {
      return {
        lean: async () => {
          findAndUpdateCalls += 1;
          if (failBeforeUpsert) {
            failBeforeUpsert = false;
            throw new Error('simulated database unavailability');
          }
          let row = rows.get(filter.operationId);
          const updatedExisting = Boolean(row);
          if (!row) {
            row = {
              _id: String(nextId++),
              timestamp: new Date('2026-10-27T00:00:00.000Z'),
              ...update.$setOnInsert,
            };
            rows.set(filter.operationId, row);
          }
          const result = {
            value: row,
            lastErrorObject: {
              updatedExisting,
              ...(updatedExisting ? {} : { upserted: row._id }),
            },
            ok: 1,
          };
          if (failAfterUpsert) {
            failAfterUpsert = false;
            throw new Error('write committed but acknowledgement was lost');
          }
          assert.equal(options.upsert, true);
          assert.equal(options.includeResultMetadata, true);
          return result;
        },
      };
    },
    async countDocuments() {
      if (metricsFailure) throw new Error('metrics query failed');
      return rows.size;
    },
  };
  const sizeGauge = { set() {} };
  const redis = {
    async setEx() {
      if (redisFailure) throw new Error('redis unavailable');
    },
  };
  const handler = createIdempotentChatSaveHandler({
    ChatHistory: model,
    chatHistorySize: sizeGauge,
    redisClient: redis,
    ensureReady: async () => {
      readyCalls += 1;
      if (ensureReadyFailure) throw new Error('index creation unavailable');
    },
    logger: { error: (...args) => logs.push(args) },
  });
  return {
    handler, rows, logs,
    get readyCalls() { return readyCalls; },
    get findAndUpdateCalls() { return findAndUpdateCalls; },
    failBeforeUpsert: () => { failBeforeUpsert = true; },
    failAfterUpsert: () => { failAfterUpsert = true; },
  };
}

function request(body = {}, key = 'chat-save-123') {
  return {
    body: {
      userId: 'user-1',
      civId: 'civ-1',
      message: 'hello',
      response: 'world',
      metadata: { attention: 1, belief: { truth: 0.8, deception: 0.2 } },
      ...body,
    },
    headers: {},
    get(name) {
      return name.toLowerCase() === 'idempotency-key' ? key : undefined;
    },
  };
}

test('canonical JSON sorts nested object keys for stable request digests', () => {
  assert.equal(canonicalJson({ z: 1, a: { y: 2, x: 3 } }), '{"a":{"x":3,"y":2},"z":1}');
  assert.equal(
    chatPayloadDigest({ userId: 'u', metadata: { b: 2, a: 1 } }),
    chatPayloadDigest({ metadata: { a: 1, b: 2 }, userId: 'u' }),
  );
});

test('rejects request without a stable idempotency key before writing', async () => {
  const fx = createFixture();
  const req = request();
  req.get = () => undefined;
  const res = responseRecorder();
  await fx.handler(req, res);
  assert.equal(res.statusCode, 400);
  assert.equal(res.body.error, 'idempotency_key_required');
  assert.equal(fx.rows.size, 0);
});

test('rejects a header/body idempotency-key mismatch', async () => {
  const fx = createFixture();
  const res = responseRecorder();
  await fx.handler(request({ operationId: 'other-id' }), res);
  assert.equal(res.statusCode, 400);
  assert.equal(res.body.error, 'idempotency_key_mismatch');
  assert.equal(fx.rows.size, 0);
});

test('first save and replay return the same Mongo record without duplication', async () => {
  const fx = createFixture();
  const first = responseRecorder();
  await fx.handler(request(), first);
  const second = responseRecorder();
  await fx.handler(request(), second);
  assert.equal(first.statusCode, 201);
  assert.equal(first.body.status, 'success');
  assert.equal(first.body.replayed, false);
  assert.equal(second.statusCode, 200);
  assert.equal(second.body.replayed, true);
  assert.equal(first.body.id, second.body.id);
  assert.equal(fx.rows.size, 1);
  assert.equal(second.body.requestDigest, first.body.requestDigest);
});

test('same operation ID with a changed payload is rejected without another write', async () => {
  const fx = createFixture();
  const first = responseRecorder();
  await fx.handler(request(), first);
  const second = responseRecorder();
  await fx.handler(request({ message: 'different operation under same key' }), second);
  assert.equal(second.statusCode, 409);
  assert.equal(second.body.error, 'idempotency_key_payload_conflict');
  assert.equal(fx.rows.size, 1);
});

test('Redis failure after Mongo commit does not become a false HTTP 500', async () => {
  const fx = createFixture({ redisFailure: true });
  const res = responseRecorder();
  await fx.handler(request(), res);
  assert.equal(res.statusCode, 201);
  assert.equal(res.body.status, 'success');
  assert.equal(res.body.ancillary.cache, 'degraded');
  assert.equal(fx.rows.size, 1);
});

test('metrics failure after Mongo commit is reported as ancillary degradation', async () => {
  const fx = createFixture({ metricsFailure: true });
  const res = responseRecorder();
  await fx.handler(request(), res);
  assert.equal(res.statusCode, 201);
  assert.equal(res.body.status, 'success');
  assert.equal(res.body.ancillary.metrics, 'degraded');
  assert.equal(fx.rows.size, 1);
});

test('database error after a committed upsert is reconciled by the same operation ID', async () => {
  const fx = createFixture();
  fx.failAfterUpsert();
  const first = responseRecorder();
  await fx.handler(request(), first);
  assert.equal(first.statusCode, 201);
  assert.equal(first.body.status, 'success');
  assert.equal(first.body.replayed, true);
  assert.equal(fx.rows.size, 1);
});

test('unconfirmed database outcome returns indeterminate and instructs same-key retry', async () => {
  const fx = createFixture();
  fx.failBeforeUpsert();
  const res = responseRecorder();
  await fx.handler(request(), res);
  assert.equal(res.statusCode, 503);
  assert.equal(res.body.status, 'indeterminate');
  assert.equal(res.body.retryWithSameKey, true);
  assert.equal(res.body.operationId, 'chat-save-123');
  assert.equal(fx.rows.size, 0);
});

test('index initialization failure fails closed before database writes', async () => {
  const fx = createFixture({ ensureReadyFailure: true });
  const res = responseRecorder();
  await fx.handler(request(), res);
  assert.equal(res.statusCode, 503);
  assert.equal(res.body.status, 'indeterminate');
  assert.equal(fx.rows.size, 0);
});

test('concurrent identical requests converge on one stable record', async () => {
  const fx = createFixture();
  const a = responseRecorder();
  const b = responseRecorder();
  await Promise.all([fx.handler(request(), a), fx.handler(request(), b)]);
  assert.equal(fx.rows.size, 1);
  assert.equal(a.body.id, b.body.id);
  assert.equal(a.body.requestDigest, b.body.requestDigest);
  assert.ok([200, 201].includes(a.statusCode));
  assert.ok([200, 201].includes(b.statusCode));
});
