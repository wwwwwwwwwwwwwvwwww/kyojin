const { getBotUrl } = require('./_lib');

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const id = req.query.id || (req.url || '').split('/api/approval/')[1]?.split('?')[0];
  if (!id) return res.status(400).json({ error: 'Missing approval ID' });

  try {
    const BOT_URL = getBotUrl();
    const resp = await fetch(`${BOT_URL}/api/approval/${encodeURIComponent(id)}`, {
      headers: { 'X-API-Key': process.env.BOT_API_KEY || '' },
    });

    const result = await resp.json();

    if (resp.ok && result.status === 'approved') {
      const secure = req.headers['x-forwarded-proto'] === 'https';
      if (result.token) {
        res.setHeader('Set-Cookie', `session=${result.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600${secure ? '; Secure' : ''}`);
      }
      return res.status(200).json({ status: 'approved' });
    }

    return res.status(200).json({ status: result.status || 'pending' });
  } catch (e) {
    return res.status(500).json({ error: 'Bot server unreachable' });
  }
};
