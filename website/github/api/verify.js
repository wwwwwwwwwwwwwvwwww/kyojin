const { BOT_URL } = require('./_lib');

module.exports = async (req, res) => {
  const code = req.query.code;
  if (!code) return res.status(400).json({ success: false, error: 'Missing code' });

  try {
    const r = await fetch(`${BOT_URL}/api/verify?code=${encodeURIComponent(code)}`);
    const data = await r.json();
    return res.status(r.status).json(data);
  } catch (e) {
    return res.status(502).json({ success: false, error: 'Bot unreachable' });
  }
};
