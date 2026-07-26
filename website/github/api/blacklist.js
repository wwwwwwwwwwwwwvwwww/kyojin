const { BOT_URL } = require('./_lib');

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const cookies = req.headers.cookie || '';

  let body = '';
  for await (const chunk of req) body += chunk;
  let data;
  try { data = JSON.parse(body); } catch { return res.status(400).json({ error: 'Invalid JSON' }); }

  try {
    const resp = await fetch(`${BOT_URL}/api/blacklist`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Cookie': cookies,
        'X-API-Key': process.env.BOT_API_KEY || '',
      },
      body: JSON.stringify(data),
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
