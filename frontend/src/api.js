/**
 * Simple fetch-based API client.
 * All requests are relative so the Vite proxy (dev) or FastAPI (prod) handles routing.
 */

const BASE = ''
const TOKEN_KEY = 'hd_api_token'

function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
}

function setToken(token) {
    try { localStorage.setItem(TOKEN_KEY, token) } catch { /* private mode: token just isn't remembered */ }
}

// If the server is protected with API_AUTH_TOKEN, attach the token to every /api request and ask for
// it once when the server answers 401. This covers both api.* calls and the pages' direct fetch() calls.
if (typeof window !== 'undefined' && !window.__hdFetchPatched) {
    window.__hdFetchPatched = true
    const nativeFetch = window.fetch.bind(window)
    window.fetch = async (input, init = {}) => {
        const url = typeof input === 'string' ? input : (input && input.url) || ''
        if (!url.startsWith('/api/')) return nativeFetch(input, init)

        const send = (token) => {
            const headers = new Headers(init.headers || {})
            if (token) headers.set('X-API-Key', token)
            return nativeFetch(input, { ...init, headers })
        }
        let res = await send(getToken())
        if (res.status === 401) {
            const token = window.prompt('This server requires an API token. Enter it to continue:')
            if (token) {
                setToken(token.trim())
                res = await send(token.trim())
            }
        }
        return res
    }
}

async function request(path, options = {}) {
    const res = await fetch(`${BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
        body: options.body ? JSON.stringify(options.body) : undefined,
    })
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail)
        throw new Error(detail || 'Request failed')
    }
    return res.json()
}

export const api = {
    getJobs: (params = {}) => {
        const qs = new URLSearchParams(params).toString()
        return request(`/api/jobs${qs ? '?' + qs : ''}`)
    },
    getJob: (id) => request(`/api/jobs/${id}`),
    getActiveJobs: () => request('/api/jobs/active'),
    deleteJob: (id) => request(`/api/jobs/${id}`, { method: 'DELETE' }),
    cancelJob: (id) => request(`/api/jobs/${id}/cancel`, { method: 'POST', body: {} }),
    retryJob: (id) => request(`/api/jobs/${id}/retry`, { method: 'POST', body: {} }),
    getLogs: (params) => {
        const filteredParams = Object.fromEntries(Object.entries(params).filter(([_, v]) => v != null && v !== ''))
        const qs = new URLSearchParams(filteredParams).toString()
        return request(`/api/logs${qs ? '?' + qs : ''}`)
    },
    deleteAllLogs: () => request('/api/logs/all', { method: 'DELETE' }),
    deleteLogsOlderThan: (days) => {
        const query = new URLSearchParams()
        query.append('days', days)
        return request(`/api/logs/older-than?${query.toString()}`, { method: 'DELETE' })
    },
    getStats: () => request('/api/stats'),
    getSyncStatus: () => request('/api/sync/status'),
    triggerDownload: (data) => request('/api/jobs/trigger', { method: 'POST', body: data }),
    triggerMonitored: () => request('/api/jobs/trigger-monitored', { method: 'POST' }),
    triggerMonitoredTV: () => request('/api/jobs/trigger-monitored?media_type=tv', { method: 'POST' }),
    triggerMissing: () => request('/api/jobs/trigger-missing', { method: 'POST' }),
    triggerDiscovery: () => request('/api/jobs/discovery', { method: 'POST' }),
    setMonitored: (id, monitored) => request(`/api/jobs/${id}/monitor`, { method: 'PUT', body: { monitored } }),
    downloadDiscovered: (id) => request(`/api/jobs/${id}/download`, { method: 'POST' }),
    // Reconcile one job (movie or episode) with live Radarr/Sonarr data
    syncMovie: (id) => request(`/api/jobs/${id}/sync`, { method: 'POST' }),
    syncAll: () => request('/api/jobs/sync-all', { method: 'POST' }),
    syncAllSonarr: () => request('/api/jobs/sync-all-sonarr', { method: 'POST' }),
    getSettings: () => request('/api/settings'),
    updateSettings: (data) => request('/api/settings', { method: 'POST', body: data }),
    testRadarr: () => request('/api/test/radarr'),
    testSonarr: () => request('/api/test/sonarr'),
    testTmdb: () => request('/api/test/tmdb'),
    importRadarr: () => request('/api/jobs/import-radarr', { method: 'POST' }),
    importSonarr: () => request('/api/jobs/import-sonarr', { method: 'POST' }),
    testQbittorrent: (data) => request('/api/settings/test-qbittorrent', { method: 'POST', body: data }),
    testLlm: (data) => request('/api/settings/test-llm', { method: 'POST', body: data }),
    importUrl: (jobId, url) => request(`/api/jobs/${jobId}/import-url`, { method: 'POST', body: { url } }),
}

/** One-line human summary of a sync response, for toasts. */
export function describeSync(res, what = 'Radarr') {
    if (!res) return `Synced with ${what}`
    if (res.state !== undefined) {
        return res.changed
            ? `Synced with ${what}: ${res.previous} → ${res.state}`
            : `Already in sync with ${what} (${res.state})`
    }
    const parts = []
    if (res.updated) parts.push(`${res.updated} updated`)
    if (res.deleted) parts.push(`${res.deleted} no longer in ${what}`)
    if (res.created) parts.push(`${res.created} added`)
    return parts.length ? `Synced with ${what}: ${parts.join(', ')}` : `Everything already in sync with ${what}`
}
