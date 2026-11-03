'use strict';
/**
 * Administrative-only middleware for CycleKernal /api/* endpoints.
 * This is service access control, NOT tenant/resource-scoped end-user authorization.
 */
const crypto = require('node:crypto');

function safeEquals(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  // Digest both sides to keep the comparison on equal-length inputs.
  const lhs = crypto.createHash('sha256').update(a, 'utf8').digest();
  const rhs = crypto.createHash('sha256').update(b, 'utf8').digest();
  return crypto.timingSafeEqual(lhs, rhs);
}

function presentedToken(req) {
  const headers = req.headers || {};
  const admin = headers['x-admin-token'];
  const auth = headers.authorization;
  if (Array.isArray(admin) || Array.isArray(auth) || (admin !== undefined && auth !== undefined)) return null;
  if (typeof admin === 'string') return admin;
  if (typeof auth !== 'string') return null;
  if (!auth.startsWith('Bearer ')) return null;
  const token = auth.slice('Bearer '.length);
  if (!token || token !== token.trim() || token.includes(' ')) return null;
  return token;
}

function privateApiGuard(req, res, next, options = {}) {
  const configured = options.token !== undefined ? options.token : process.env.CK_API_ADMIN_TOKEN;
  if (typeof configured !== 'string' || !configured || !configured.trim()) {
    return res.status(503).json({ status: 'error', error: 'private API unavailable: CK_API_ADMIN_TOKEN not configured' });
  }
  // A single operator token is deliberately not claimed to identify an end user.
  const presented = presentedToken(req);
  if (!safeEquals(presented, configured)) {
    return res.status(401).json({ status: 'error', error: 'authentication required' });
  }
  return next();
}

module.exports = { privateApiGuard, presentedToken, safeEquals };
