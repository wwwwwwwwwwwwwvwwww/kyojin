const { BOT_URL } = require('./_lib');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const cookies = req.headers.cookie || '';
  const body = req.body || {};

  try {
    const resp = await fetch(`${BOT_URL}/api/logs/dismiss-all`, {
      method: 'POST',
      headers: {
        'Cookie': cookies,
        'X-API-Key': process.env.BOT_API_KEY || '',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    const result = await resp.json();
    return res.status(resp.status).json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Bot server unreachable' });
  }
};
