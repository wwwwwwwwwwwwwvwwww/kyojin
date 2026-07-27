const { getBotUrl } = require('./_lib');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

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
      },
      body: JSON.stringify({ user_id: userId, key }),
    });

    const result = await resp.json();
    const setCookie = resp.headers.get('set-cookie');
    if (setCookie) {
      res.setHeader('Set-Cookie', setCookie);
    }
    return res.status(resp.status).json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Bot server unreachable' });
  }
};
