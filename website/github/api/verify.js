const { getBotUrl } = require('./_lib');

module.exports = async (req, res) => {
  const code = req.query.code;
  const state = req.query.state;
  if (!code) return res.status(400).json({ success: false, error: 'Missing code' });

  try {
    const BOT_URL = getBotUrl();
    let url = `${BOT_URL}/api/verify?code=${encodeURIComponent(code)}`;
    if (state) {
      url += `&state=${encodeURIComponent(state)}`;
    }
    const r = await fetch(url);
    const data = await r.json();
    return res.status(r.status).json(data);
  } catch (e) {
    return res.status(502).json({ success: false, error: 'Bot unreachable' });
  }
};
