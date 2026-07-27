const { getBotUrl } = require('./_lib');

module.exports = async function handler(req, res) {
  const cookies = req.headers.cookie || '';

  try {
    const BOT_URL = getBotUrl();
    const resp = await fetch(`${BOT_URL}/api/session`, {
      headers: {
        'Cookie': cookies,
        'X-API-Key': process.env.BOT_API_KEY || '',
      },
    });
    const result = await resp.json();
    return res.status(resp.status).json(result);
  } catch (e) {
    return res.status(200).json({ authenticated: false });
  }
};
