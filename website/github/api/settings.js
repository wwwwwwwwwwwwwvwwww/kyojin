const { BOT_URL } = require('./_lib');

module.exports = async function handler(req, res) {
  const cookies = req.headers.cookie || '';

  try {
    let body = undefined;
    if (req.method === 'POST') {
      body = await new Promise((resolve) => {
        let data = '';
        req.on('data', (chunk) => { data += chunk; });
        req.on('end', () => resolve(data || null));
      });
    }

    const resp = await fetch(`${BOT_URL}/api/settings`, {
      method: req.method,
      headers: {
        'Content-Type': 'application/json',
        'Cookie': cookies,
        'X-API-Key': process.env.BOT_API_KEY || '',
      },
      body,
    });
    const result = await resp.json();

    if (resp.status === 401) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    return res.status(200).json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Bot server unreachable' });
  }
};
