const { getBotUrl } = require('./_lib');

const RATE_LIMITS = {};

function checkRate(ip) {
  const now = Date.now();
  RATE_LIMITS[ip] = (RATE_LIMITS[ip] || []).filter(t => now - t < 60000);
  if (RATE_LIMITS[ip].length >= 10) return false;
  RATE_LIMITS[ip].push(now);
  return true;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const ip = req.headers['x-forwarded-for'] || req.socket.remoteAddress || '';
  if (!checkRate(ip)) return res.status(429).json({ error: 'Rate limited' });

  let body = '';
  for await (const chunk of req) body += chunk;
  let data;
  try { data = JSON.parse(body); } catch { return res.status(400).json({ error: 'Invalid JSON' }); }

  const userId = String(data.user_id || '').trim();
  const key = String(data.key || '').trim();
  if (!userId || !key) return res.status(400).json({ error: 'Missing user ID or key' });

  try {
    const BOT_URL = getBotUrl();
    const resp = await fetch(`${BOT_URL}/api/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': process.env.BOT_API_KEY || '',
      },
      body: JSON.stringify({ user_id: userId, key }),
    });

    const result = await resp.json();
    return res.status(resp.status).json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Bot server unreachable' });
  }
};
