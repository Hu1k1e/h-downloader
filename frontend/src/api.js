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
    retryJob: (id) => request(`/api/jobs/${id}/retry`, { method: 'POST', body: {} }),
    // Background Jellyseerr sync (picks up new approved requests)
    syncJellyseerr: () => request('/api/jobs/sync', { method: 'POST' }),
    // Synchronous Radarr status sync — reflects updated state immediately in response
    syncRadarrStatus: () => request('/api/jobs/sync-radarr', { method: 'POST' }),
    getLogs: (params) => {
        const qs = new URLSearchParams(params).toString()
        return request(`/api/logs${qs ? '?' + qs : ''}`)
    },
    deleteLogs: (olderThanDays) => {
        const query = new URLSearchParams()
        if (olderThanDays) query.append('older_than_days', olderThanDays)
        return request(`/api/logs?${query.toString()}`, { method: 'DELETE' })
    },
    getStats: () => request('/api/stats'),
    triggerDownload: (data) => request('/api/jobs/trigger', { method: 'POST', body: data }),
    triggerMonitored: () => request('/api/jobs/trigger-monitored', { method: 'POST' }),
    triggerMissing: () => request('/api/jobs/trigger-missing', { method: 'POST' }),
    getSettings: () => request('/api/settings'),
    updateSettings: (data) => request('/api/settings', { method: 'POST', body: data }),
    testRadarr: () => request('/api/test/radarr'),
    testTmdb: () => request('/api/test/tmdb'),
    importRadarr: () => request('/api/jobs/import-radarr', { method: 'POST' }),
    testQbittorrent: (data) => request('/api/settings/test-qbittorrent', { method: 'POST', body: data }),
}
