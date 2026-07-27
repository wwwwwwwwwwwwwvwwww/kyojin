const { getBotUrl } = require('./_lib');

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const cookies = req.headers.cookie || '';

  try {
    const BOT_URL = getBotUrl();
    const resp = await fetch(`${BOT_URL}/api/logs`, {
      headers: {
        'Cookie': cookies,
        'X-API-Key': process.env.BOT_API_KEY || '',
      },
    });
    const result = await resp.json();
    return res.status(200).json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Bot server unreachable' });
  }
};
