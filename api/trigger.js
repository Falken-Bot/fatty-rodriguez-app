export default async function handler(req, res) {
  // Only allow POST requests
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const GITHUB_USERNAME = process.env.GH_USERNAME;
  const GITHUB_REPO = "fatty-rodriguez-app";
  const GITHUB_TOKEN = process.env.GH_PAT_TOKEN;

  try {
    const response = await fetch(`https://api.github.com/repos/${GITHUB_USERNAME}/${GITHUB_REPO}/actions/workflows/daily_scan.yml/dispatches`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'Vercel-Serverless-Function'
      },
      body: JSON.stringify({ ref: 'main' })
    });

    if (response.ok) {
      return res.status(200).json({ success: true, message: "GitHub Actions workflow dispatched successfully!" });
    } else {
      const errText = await response.text();
      return res.status(500).json({ error: "Failed to dispatch workflow", details: errText });
    }
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
