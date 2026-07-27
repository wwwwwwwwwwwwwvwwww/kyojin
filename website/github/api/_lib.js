const crypto = require('crypto');

const SECRET = process.env.SESSION_SECRET || 'jinn-default-secret-change-me';
const ADMIN_HASH = process.env.ADMIN_PASSWORD_HASH || '6958f2c65a4d20915286ebd1fed07e0a83c1f9a84ea4ba3362cbd1d6bfa50e02';
const BOT_URL = process.env.BOT_URL || '';

function getBotUrl() {
  if (!BOT_URL) {
    throw new Error('BOT_URL is not configured. Set BOT_URL in Vercel to your bot server URL.');
  }
  return BOT_URL;
}

function sign(payload) {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig = crypto.createHmac('sha256', SECRET).update(header + '.' + body).digest('base64url');
  return `${header}.${body}.${sig}`;
}

function verify(token) {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  const [header, body, sig] = parts;
  const expected = crypto.createHmac('sha256', SECRET).update(header + '.' + body).digest('base64url');
  if (sig !== expected) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString());
    if (payload.exp && Date.now() / 1000 > payload.exp) return null;
    return payload;
  } catch { return null; }
}

module.exports = { sign, verify, ADMIN_HASH, getBotUrl, BOT_URL };
