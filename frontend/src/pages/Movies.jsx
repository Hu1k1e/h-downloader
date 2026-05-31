import { useState, useEffect } from 'react'
import { api } from '../api'

const STATUS_COLOR = {
    done: 'var(--success)',
    downloading: '#3b82f6',
    searching: 'var(--warning)',
    failed: 'var(--error)',
    not_found: 'var(--text-muted)',
    pending: '#3b82f6',
    checking_radarr: '#3b82f6',
    importing: 'var(--warning)',
    skipped: 'var(--text-muted)',
    movie_missing: '#ef4444',
}

const STATUS_LABEL = {
    done: 'Available',
    downloading: 'Downloading',
    searching: 'Searching',
    failed: 'Failed',
    not_found: 'Not Found',
    pending: 'Downloading on Server',
    checking_radarr: 'Downloading on Server',
    importing: 'Importing',
    skipped: 'Skipped',
    movie_missing: 'File Missing',
}

// Base Filter tabs definition
const BASE_TABS = [
    { key: 'all', label: 'All' },
    { key: 'available', label: 'Available' },
    { key: 'radarr', label: 'Downloading on Server' },
    { key: 'movie_missing', label: 'File Missing' },
    { key: 'unmonitored', label: 'Unmonitored' },
]

function matchesTab(movie, tab) {
    const s = movie.status
    if (tab === 'all') return true
    if (tab === 'available') return s === 'done'
    if (tab === 'radarr') return s === 'pending' || s === 'checking_radarr'
    if (tab === 'movie_missing') return s === 'movie_missing'
    if (tab === 'unmonitored') return !movie.monitored
    if (tab.startsWith('lang_')) return movie.language === tab.replace('lang_', '')
    return true
}

function tabCount(moviesList, tab) {
    return moviesList.filter(m => matchesTab(m, tab)).length
}

function PosterCard({ movie, onTrigger, onDelete, onToggleMonitor }) {
    const status = (movie.status || '').toLowerCase()
    const colour = STATUS_COLOR[status] || 'var(--text-muted)'
    const label = STATUS_LABEL[status] || status.toUpperCase()

    const posterSrc = movie.poster_path
        ? `https://image.tmdb.org/t/p/w300${movie.poster_path}`
        : null

    return (
        <div className="poster-card">
            <div className="poster-img-wrap">
                {posterSrc ? (
                    <img
                        src={posterSrc}
                        alt={movie.title}
                        className="poster-img"
                        onError={e => {
                            e.target.onerror = null
                            e.target.replaceWith(
                                Object.assign(document.createElement('div'), {
                                    className: 'poster-placeholder',
                                    textContent: movie.title?.charAt(0) || '?'
                                })
                            )
                        }}
                    />
                ) : (
                    <div className="poster-placeholder">
                        {movie.title?.charAt(0) || '?'}
                    </div>
                )}
                {/* Status bar overlay */}
                <div className="poster-status-bar" style={{ '--status-color': colour }}>
                    <span className="poster-status-label">{label}</span>
                    {status === 'downloading' && movie.progress_pct > 0 && (
                        <div className="poster-progress-wrap">
                            <div
                                className="poster-progress-fill"
                                style={{ width: `${movie.progress_pct}%` }}
                            />
                        </div>
                    )}
                </div>
                {/* Monitored / Missing indicator dot */}
                {movie.monitored && (
                    <div
                        className={`poster-monitored-dot${status === 'movie_missing' ? ' poster-monitored-dot--missing' : ''}`}
                        title={status === 'movie_missing' ? 'File missing from Radarr folder' : 'Monitored'}
                    />
                )}
            </div>

            <div className="poster-info">
                <div className="poster-title" title={movie.title}>{movie.title}</div>
                <div className="poster-meta">
                    {movie.media_type === 'series' && movie.season_number && movie.episode_number ? (
                        <span className="poster-lang" style={{ background: '#3b82f6' }}>S{String(movie.season_number).padStart(2, '0')}E{String(movie.episode_number).padStart(2, '0')}</span>
                    ) : movie.year ? (
                        <span>{movie.year}</span>
                    ) : null}
                    {movie.language && (
                        <span className="poster-lang">{movie.language}</span>
                    )}
                </div>
            </div>

            <div className="poster-actions">
                <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => onToggleMonitor(movie.id, movie.monitored)}
                    title={movie.monitored ? 'Unmonitor' : 'Re-monitor'}
                    style={{ flex: 1 }}
                >
                    {movie.monitored ? 'Unmonitor' : 'Monitor'}
                </button>
                <button
                    className="btn btn-primary btn-sm"
                    onClick={() => onTrigger(movie.id, movie.tmdb_id, movie.language)}
                    disabled={status === 'downloading' || status === 'importing'}
                    title="Force Einthusan search"
                    style={{ flex: 1 }}
                >
                    ▶
                </button>
                <button
                    className="btn btn-danger btn-sm"
                    onClick={() => onDelete(movie.id)}
                    title="Delete"
                >
                    ✕
                </button>
            </div>
        </div>
    )
}

export default function Movies({ mediaType = 'movie' }) {
    const [movies, setMovies] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [isTriggering, setIsTriggering] = useState(false)
    const [isSyncing, setIsSyncing] = useState(false)
    const [search, setSearch] = useState('')
    const [activeTab, setActiveTab] = useState('all')

    const fetchMovies = async () => {
        try {
            const res = await fetch('/api/jobs')
            if (!res.ok) throw new Error('Failed to fetch movies')
            const data = await res.json()
            setMovies(data)
            setError(null)
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchMovies()
        const interval = setInterval(fetchMovies, 5000)
        return () => clearInterval(interval)
    }, [])

    const toggleMonitor = async (id, currentStatus) => {
        try {
            await fetch(`/api/jobs/${id}/monitor`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ monitored: !currentStatus })
            })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const triggerMonitored = async () => {
        setIsTriggering(true)
        try {
            await api.triggerMonitored()
            fetchMovies()
        } catch (err) { console.error(err) }
        finally { setIsTriggering(false) }
    }

    const triggerMissing = async () => {
        setIsTriggering(true)
        try {
            await api.triggerMissing()
            fetchMovies()
        } catch (err) { console.error(err) }
        finally { setIsTriggering(false) }
    }

    const syncJellyseerr = async () => {
        setIsSyncing(true)
        setError(null)
        try {
            // Radarr status sync runs INLINE on the server.
            // DB is committed before the response returns,
            // so fetchMovies() immediately after sees correct statuses.
            await api.syncRadarrStatus()
            // Also kick off background Jellyseerr sync for new approved requests
            api.syncJellyseerr().catch(e => console.warn("Jellyseerr bg sync:", e))
            await fetchMovies()
        } catch (err) {
            console.error("Sync failed:", err)
            setError(err.message)
        } finally {
            setIsSyncing(false)
        }
    }

    const deleteJob = async (id) => {
        if (!confirm('Delete this job?')) return
        try {
            await fetch(`/api/jobs/${id}`, { method: 'DELETE' })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const triggerJob = async (id, tmdbId, lang) => {
        try {
            await fetch('/api/jobs/trigger', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tmdb_id: tmdbId, language: lang })
            })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const typeMovies = movies.filter(m => (m.media_type || 'movie') === mediaType)

    const filtered = typeMovies.filter(m => {
        const matchSearch = m.title.toLowerCase().includes(search.toLowerCase())
        const matchTab = matchesTab(m, activeTab)
        return matchSearch && matchTab
    })

    const uniqueLangs = [...new Set(typeMovies.map(m => m.language).filter(Boolean))].sort()
    const dynamicTabs = [
        ...BASE_TABS,
        ...uniqueLangs.map(lang => ({ key: `lang_${lang}`, label: lang.charAt(0).toUpperCase() + lang.slice(1) }))
    ]

    return (
        <div className="main-content">
            {/* Header */}
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">{mediaType === 'series' ? 'Series' : 'Movies'}</h1>
                    <p className="page-subtitle">{typeMovies.length} tracked · {typeMovies.filter(m => m.monitored).length} monitored</p>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-secondary" onClick={syncJellyseerr} disabled={isSyncing}>
                        {isSyncing ? 'Syncing...' : 'Sync Requests'}
                    </button>
                    <button className="btn btn-primary" onClick={triggerMissing} disabled={isTriggering || typeMovies.length === 0}>
                        {isTriggering ? 'Triggering...' : 'Trigger Missing'}
                    </button>
                    <button className="btn btn-primary" onClick={triggerMonitored} disabled={isTriggering || typeMovies.length === 0}>
                        {isTriggering ? 'Triggering...' : 'Trigger Monitored'}
                    </button>
                </div>
            </div>

            {error && (
                <div style={{ background: 'var(--error-light)', color: 'var(--error)', padding: '12px 16px', borderRadius: 8, marginBottom: 16 }}>
                    {error}
                </div>
            )}

            {/* Filter tabs + search */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
                {/* Tab row */}
                <div className="filter-tabs" style={{ display: 'flex', flexWrap: 'wrap' }}>
                    {dynamicTabs.map(tab => {
                        const count = tabCount(typeMovies, tab.key)
                        return (
                            <button
                                key={tab.key}
                                className={`filter-tab${activeTab === tab.key ? ' active' : ''}`}
                                onClick={() => setActiveTab(tab.key)}
                            >
                                {tab.label}
                                {count > 0 && (
                                    <span className="filter-tab-count">{count}</span>
                                )}
                            </button>
                        )
                    })}
                </div>
                {/* Search */}
                <input
                    className="filter-search"
                    placeholder={`Search ${mediaType === 'series' ? 'series' : 'movies'}...`}
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
            </div>

            {/* Poster grid */}
            {loading && movies.length === 0 ? (
                <div className="empty-state">
                    <div className="spinner" style={{ width: 28, height: 28, margin: '0 auto 16px' }} />
                    <div className="empty-state-text">Loading {mediaType === 'series' ? 'series' : 'movies'}...</div>
                </div>
            ) : filtered.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-state-icon" style={{ fontSize: 40 }}>{mediaType === 'series' ? '📺' : '🎬'}</div>
                    <div className="empty-state-text">No {mediaType === 'series' ? 'series' : 'movies'} found</div>
                    <div className="empty-state-sub">
                        {activeTab !== 'all'
                            ? 'No movies in this category.'
                            : 'Approve a request in Jellyseerr to get started.'}
                    </div>
                </div>
            ) : (
                <div className="poster-grid">
                    {filtered.map(movie => (
                        <PosterCard
                            key={movie.id}
                            movie={movie}
                            onTrigger={triggerJob}
                            onDelete={deleteJob}
                            onToggleMonitor={toggleMonitor}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
