/**
 * Simple fetch-based API client.
 * All requests are relative so the Vite proxy (dev) or FastAPI (prod) handles routing.
 */

const BASE = ''

async function request(path, options = {}) {
    const res = await fetch(`${BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
        body: options.body ? JSON.stringify(options.body) : undefined,
    })
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || 'Request failed')
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
    // Background Jellyseerr sync (picks up new approved requests)
    syncJellyseerr: () => request('/api/jobs/sync', { method: 'POST' }),
    // Synchronous Radarr status sync — reflects updated state immediately in response
    syncRadarrStatus: () => request('/api/jobs/sync-radarr', { method: 'POST' }),
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
    triggerDownload: (data) => request('/api/jobs/trigger', { method: 'POST', body: data }),
    triggerMonitored: () => request('/api/jobs/trigger-monitored', { method: 'POST' }),
    triggerMissing: () => request('/api/jobs/trigger-missing', { method: 'POST' }),
    triggerDiscovery: () => request('/api/jobs/discovery', { method: 'POST' }),
    syncMovie: (id) => request(`/api/jobs/${id}/sync`, { method: 'POST' }),
    syncAll: async () => {
        const res = await fetch('/api/jobs/sync-all', { method: 'POST' })
        if (!res.ok) throw new Error('Sync all failed')
        return res.json()
    },
    syncAllSonarr: async () => {
        const res = await fetch('/api/jobs/sync-all-sonarr', { method: 'POST' })
        if (!res.ok) throw new Error('Sync all Sonarr failed')
        return res.json()
    },
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
