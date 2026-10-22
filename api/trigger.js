export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Credentials', true);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
    res.setHeader(
        'Access-Control-Allow-Headers',
        'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-Type, Date, X-Api-Version'
    );

    if (req.method === 'OPTIONS') {
        res.status(200).end();
        return;
    }

    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
    const OWNER = process.env.GITHUB_OWNER;
    const REPO = process.env.GITHUB_REPO;
    const WORKFLOW_ID = 'main.yml'; // <-- CHECK THIS FILENAME MATCHES YOUR GITHUB REPO EXACTLY
    const BRANCH = 'main';          // <-- CHECK IF YOUR DEFAULT BRANCH IS 'main' OR 'master'

    if (!GITHUB_TOKEN || !OWNER || !REPO) {
        return res.status(500).json({ 
            error: 'Missing server environment variables in Vercel.' 
        });
    }

    const targetUrl = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_ID}/dispatches`;

    try {
        const response = await fetch(targetUrl, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github+json',
                'Content-Type': 'application/json',
                'X-GitHub-Api-Version': '2022-11-28'
            },
            body: JSON.stringify({ ref: BRANCH })
        });

        if (!response.ok) {
            const errorText = await response.text();
            return res.status(response.status).json({ 
                error: `GitHub 404/Error at [${targetUrl}]: ${errorText}` 
            });
        }

        return res.status(200).json({ success: true, message: 'Workflow scan dispatched successfully.' });
    } catch (err) {
        return res.status(500).json({ error: err.message });
    }
}
