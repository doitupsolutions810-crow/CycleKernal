'use strict';

const { createHash } = require('node:crypto');

const OPERATION_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return '[' + value.map((item) => item === undefined ? 'null' : canonicalJson(item)).join(',') + ']';
  }
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value)
      .filter((key) => value[key] !== undefined)
      .sort()
      .map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key]))
      .join(',') + '}';
  }
  const encoded = JSON.stringify(value);
  return encoded === undefined ? 'null' : encoded;
}

function chatPayloadDigest(payload) {
  return createHash('sha256').update(canonicalJson(payload), 'utf8').digest('hex');
}

function idempotencyConflict(res, operationId) {
  return res.status(409).json({
    status: 'error',
    error: 'idempotency_key_payload_conflict',
    operationId,
    retryWithSamePayloadOnly: true,
  });
}

function indeterminate(res, operationId) {
  return res.status(503).json({
    status: 'indeterminate',
    error: 'chat_save_outcome_unknown',
    operationId,
    retryWithSameKey: true,
  });
}

async function queryLean(query) {
  const leanQuery = query && typeof query.lean === 'function' ? query.lean() : query;
  return await leanQuery;
}

function createIdempotentChatSaveHandler({
  ChatHistory,
  chatHistorySize,
  redisClient,
  ensureReady = async () => {},
  logger = console,
}) {
  if (!ChatHistory || typeof ChatHistory.findOne !== 'function' ||
      typeof ChatHistory.findOneAndUpdate !== 'function') {
    throw new TypeError('ChatHistory model is required');
  }

  return async function saveChat(req, res) {
    const body = req && req.body;
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      return res.status(400).json({ status: 'error', error: 'request_body_must_be_object' });
    }

    const headerKey = typeof req.get === 'function'
      ? String(req.get('Idempotency-Key') || '').trim()
      : String(req.headers?.['idempotency-key'] || req.headers?.['Idempotency-Key'] || '').trim();
    const bodyKey = body.operationId ?? body.operation_id ?? '';
    if (headerKey && bodyKey && headerKey !== bodyKey) {
      return res.status(400).json({
        status: 'error',
        error: 'idempotency_key_mismatch',
      });
    }
    const operationId = headerKey || String(bodyKey || '').trim();
    if (!OPERATION_ID_PATTERN.test(operationId)) {
      return res.status(400).json({
        status: 'error',
        error: 'idempotency_key_required',
        message: 'Send a stable Idempotency-Key header or operationId field; reuse it for retries.',
      });
    }

    const { userId, civId, message, response, metadata } = body;
    if (typeof userId !== 'string' || !userId.trim()) {
      return res.status(400).json({ status: 'error', error: 'user_id_required', operationId });
    }

    const payload = { userId, civId, message, response, metadata };
    const requestDigest = chatPayloadDigest(payload);
    const filter = { operationId };
    const insert = {
      operationId,
      requestDigest,
      userId,
      civId,
      message,
      response,
      metadata,
    };

    let chatEntry;
    let replayed = false;
    try {
      // Ensure the sparse unique index exists before relying on it for concurrent
      // upserts. The model's init promise is cached by Mongoose.
      await ensureReady();
      const existing = await queryLean(ChatHistory.findOne(filter));
      if (existing) {
        if (existing.requestDigest !== requestDigest) {
          return idempotencyConflict(res, operationId);
        }
        chatEntry = existing;
        replayed = true;
      } else {
        try {
          chatEntry = await queryLean(ChatHistory.findOneAndUpdate(
            filter,
            { $setOnInsert: insert },
            { new: true, upsert: true, runValidators: true, setDefaultsOnInsert: true },
          ));
        } catch (writeError) {
          // Duplicate-key can be a concurrent identical request; other database
          // errors can also occur after a write committed but its acknowledgement
          // was lost. Read by the same idempotency key before classifying outcome.
          let persisted;
          try {
            persisted = await queryLean(ChatHistory.findOne(filter));
          } catch {
            return indeterminate(res, operationId);
          }
          if (!persisted) {
            logger.error?.('Chat save outcome is indeterminate', writeError);
            return indeterminate(res, operationId);
          }
          if (persisted.requestDigest !== requestDigest) {
            return idempotencyConflict(res, operationId);
          }
          chatEntry = persisted;
          replayed = true;
        }

        if (!chatEntry) {
          const persisted = await queryLean(ChatHistory.findOne(filter));
          if (!persisted) return indeterminate(res, operationId);
          if (persisted.requestDigest !== requestDigest) {
            return idempotencyConflict(res, operationId);
          }
          chatEntry = persisted;
          replayed = true;
        }
        if (chatEntry.requestDigest !== requestDigest || chatEntry.operationId !== operationId) {
          return idempotencyConflict(res, operationId);
        }
      }
    } catch (error) {
      logger.error?.('Chat save primary write/lookup failed', error);
      // The database might have committed before a transport or acknowledgement
      // error. The caller must retry with the same operation ID, never a new one.
      return indeterminate(res, operationId);
    }

    const ancillary = { metrics: 'ok', cache: 'ok' };
    try {
      const totalChats = await ChatHistory.countDocuments();
      chatHistorySize?.set(totalChats);
    } catch (error) {
      ancillary.metrics = 'degraded';
      logger.error?.('Chat save succeeded but metrics refresh failed', error);
    }

    try {
      if (!redisClient || typeof redisClient.setEx !== 'function') {
        throw new Error('Redis cache client is unavailable');
      }
      await redisClient.setEx(
        `chat:${userId}:latest`,
        3600,
        JSON.stringify({ message, response, operationId, timestamp: chatEntry.timestamp || new Date() }),
      );
    } catch (error) {
      ancillary.cache = 'degraded';
      logger.error?.('Chat save succeeded but Redis cache refresh failed', error);
    }

    return res.status(replayed ? 200 : 201).json({
      status: 'success',
      id: String(chatEntry._id),
      operationId,
      replayed,
      requestDigest,
      ancillary,
    });
  };
}

module.exports = {
  canonicalJson,
  chatPayloadDigest,
  createIdempotentChatSaveHandler,
};
