/**
 * js/db.js — GitHub API Wrapper for lighting.ai
 *
 * All DB persistence goes through the GitHub Contents API.
 * The browser talks directly to api.github.com (no backend).
 */

const GITHUB_API = 'https://api.github.com';

/** SHA cache: path → sha (kept in sync after every read/write) */
const shaCache = {};

/**
 * Build standard headers for GitHub API requests.
 * @param {string} token - GitHub Personal Access Token
 */
function headers(token) {
  return {
    'Authorization': `token ${token}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };
}

/**
 * UTF-8-safe Base64 encode (handles non-ASCII chars).
 * @param {string} str
 * @returns {string}
 */
function utf8ToBase64(str) {
  return btoa(unescape(encodeURIComponent(str)));
}

/**
 * UTF-8-safe Base64 decode.
 * @param {string} b64
 * @returns {string}
 */
function base64ToUtf8(b64) {
  return decodeURIComponent(escape(atob(b64)));
}

/**
 * Load a JSON file from a GitHub repo.
 *
 * @param {string} repo  - "owner/repo"
 * @param {string} path  - file path inside the repo, e.g. "db/lighting-ai-db.json"
 * @param {string} token - GitHub PAT
 * @returns {Promise<{data: object, sha: string}>}
 */
export async function loadDB(repo, path, token) {
  const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
  const res = await fetch(url, { headers: headers(token) });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(`GitHub GET ${res.status}: ${body.message || res.statusText}`);
  }

  const json = await res.json();
  const content = base64ToUtf8(json.content.replace(/\n/g, ''));
  const data = JSON.parse(content);
  const sha = json.sha;

  shaCache[path] = sha;
  return { data, sha };
}

/**
 * Save a JSON file to a GitHub repo (PUT with SHA for updates).
 * Retries once on 409 Conflict (stale SHA) by re-fetching the latest SHA.
 *
 * @param {string} repo
 * @param {string} path
 * @param {string} token
 * @param {object} data   - the object to serialize as JSON
 * @param {string} sha    - current SHA of the file (from loadDB or previous save)
 * @param {string} [message] - commit message
 * @returns {Promise<string>} new SHA after the commit
 */
export async function saveDB(repo, path, token, data, sha, message) {
  const content = utf8ToBase64(JSON.stringify(data, null, 2));
  const commitMsg = message || `Update ${path} via lighting.ai`;

  async function doPut(currentSha) {
    const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
    const res = await fetch(url, {
      method: 'PUT',
      headers: headers(token),
      body: JSON.stringify({
        message: commitMsg,
        content,
        sha: currentSha,
      }),
    });

    if (res.status === 409) {
      return null; // conflict — caller should retry
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(`GitHub PUT ${res.status}: ${body.message || res.statusText}`);
    }

    const json = await res.json();
    return json.content.sha;
  }

  // First attempt
  let newSha = await doPut(sha);

  // Retry on 409 Conflict: re-fetch latest SHA and try again
  if (newSha === null) {
    const latest = await loadDB(repo, path, token);
    newSha = await doPut(latest.sha);
    if (newSha === null) {
      throw new Error('GitHub 409 Conflict: could not resolve after retry');
    }
  }

  shaCache[path] = newSha;
  return newSha;
}

/**
 * Upload a binary file (e.g. MP3) to GitHub as Base64.
 * Creates the file if it doesn't exist, updates if it does.
 *
 * @param {string} repo
 * @param {string} path   - e.g. "audio/5Ij0Ns/5Ij0Ns_P003/bar_001.mp3"
 * @param {string} token
 * @param {string} base64content - the file content already Base64-encoded
 * @param {string} [message]
 * @returns {Promise<string>} SHA of the committed file
 */
export async function uploadFile(repo, path, token, base64content, message) {
  const commitMsg = message || `Upload ${path} via lighting.ai`;

  // Check if file exists to get its SHA
  let existingSha = shaCache[path] || null;
  if (!existingSha) {
    try {
      const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
      const res = await fetch(url, { headers: headers(token) });
      if (res.ok) {
        const json = await res.json();
        existingSha = json.sha;
      }
    } catch {
      // file doesn't exist yet — that's fine
    }
  }

  const url = `${GITHUB_API}/repos/${repo}/contents/${path}`;
  const body = {
    message: commitMsg,
    content: base64content,
  };
  if (existingSha) {
    body.sha = existingSha;
  }

  const res = await fetch(url, {
    method: 'PUT',
    headers: headers(token),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(`GitHub PUT ${res.status}: ${errBody.message || res.statusText}`);
  }

  const json = await res.json();
  const newSha = json.content.sha;
  shaCache[path] = newSha;
  return newSha;
}

/**
 * Load DB via direct fetch (no token needed).
 * Works on GitHub Pages (same-origin) and local dev servers.
 * Returns data only — no SHA (read-only mode).
 *
 * @param {string} path - relative path, e.g. "db/lighting-ai-db.json"
 * @returns {Promise<{data: object, sha: null}>}
 */
export async function loadDBLocal(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`Fetch ${res.status}: ${res.statusText}`);
  }
  const data = await res.json();
  return { data, sha: null };
}

/**
 * Test the GitHub connection by reading the repo root.
 *
 * @param {string} repo
 * @param {string} token
 * @returns {Promise<boolean>}
 */
export async function testConnection(repo, token) {
  const url = `${GITHUB_API}/repos/${repo}`;
  const res = await fetch(url, { headers: headers(token) });
  return res.ok;
}

/**
 * Get cached SHA for a path.
 * @param {string} path
 * @returns {string|null}
 */
export function getSha(path) {
  return shaCache[path] || null;
}
