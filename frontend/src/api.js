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
    deleteJob: (id) => request(`/api/jobs/${id}`, { method: 'DELETE' }),
    retryJob: (id) => request(`/api/jobs/${id}/retry`, { method: 'POST', body: {} }),
    syncJellyseerr: () => request('/api/jobs/sync', { method: 'POST' }),
    getStats: () => request('/api/stats'),
    triggerDownload: (data) => request('/api/jobs/trigger', { method: 'POST', body: data }),
    getSettings: () => request('/api/settings'),
    updateSettings: (data) => request('/api/settings', { method: 'POST', body: data }),
    testRadarr: () => request('/api/test/radarr'),
    testTmdb: () => request('/api/test/tmdb'),
}
