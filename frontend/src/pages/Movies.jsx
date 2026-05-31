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

const BASE_TABS = [
    { key: 'all', label: 'All' },
    { key: 'available', label: 'Available' },
    { key: 'radarr', label: 'Downloading on Server' },
    { key: 'movie_missing', label: 'File Missing' },
    { key: 'unmonitored', label: 'Unmonitored' },
]

function matchesFilters(movie, filters) {
    if (filters.length === 0 || filters.includes('all')) return true;
    
    // OR logic across all selected filters
    return filters.some(tab => {
        const s = movie.status
        if (tab === 'available') return s === 'done'
        if (tab === 'radarr') return s === 'pending' || s === 'checking_radarr'
        if (tab === 'movie_missing') return s === 'movie_missing'
        if (tab === 'unmonitored') return !movie.monitored
        if (tab.startsWith('lang_')) return movie.language === tab.replace('lang_', '')
        return false
    })
}

function getPosterSrc(path) {
    if (!path) return null;
    return path.startsWith('http') ? path : `https://image.tmdb.org/t/p/w300${path}`;
}

function PosterCard({ movie, onTrigger, onDelete, onToggleMonitor }) {
    const status = (movie.status || '').toLowerCase()
    const colour = STATUS_COLOR[status] || 'var(--text-muted)'
    const label = STATUS_LABEL[status] || status.toUpperCase()
    const posterSrc = getPosterSrc(movie.poster_path)

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
                <div className="poster-status-bar" style={{ '--status-color': colour }}>
                    <span className="poster-status-label">{label}</span>
                    {status === 'downloading' && movie.progress_pct > 0 && (
                        <div className="poster-progress-wrap">
                            <div className="poster-progress-fill" style={{ width: `${movie.progress_pct}%` }} />
                        </div>
                    )}
                </div>
                {movie.monitored && (
                    <div
                        className={`poster-monitored-dot${status === 'movie_missing' ? ' poster-monitored-dot--missing' : ''}`}
                        title={status === 'movie_missing' ? 'File missing' : 'Monitored'}
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
                <button className="btn btn-secondary btn-sm" onClick={() => onToggleMonitor(movie.id, movie.monitored)} style={{ flex: 1 }}>
                    {movie.monitored ? 'Unmonitor' : 'Monitor'}
                </button>
                <button className="btn btn-primary btn-sm" onClick={() => onTrigger(movie.id, movie.tmdb_id, movie.language, movie.media_type, movie.season_number, movie.episode_number)} disabled={status === 'downloading' || status === 'importing'} title="Force Scraper Search" style={{ flex: 1 }}>
                    ▶
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onDelete(movie.id)} title="Delete">
                    ✕
                </button>
            </div>
        </div>
    )
}

function SeriesCard({ series, onClick }) {
    // series is an array of episodes
    const rep = series[0] // representative episode
    const posterSrc = getPosterSrc(rep.poster_path)
    const monitoredCount = series.filter(e => e.monitored).length
    const availableCount = series.filter(e => e.status === 'done').length

    return (
        <div className="poster-card" onClick={onClick} style={{ cursor: 'pointer' }}>
            <div className="poster-img-wrap">
                {posterSrc ? (
                    <img
                        src={posterSrc}
                        alt={rep.title}
                        className="poster-img"
                        onError={e => {
                            e.target.onerror = null
                            e.target.replaceWith(
                                Object.assign(document.createElement('div'), {
                                    className: 'poster-placeholder',
                                    textContent: rep.title?.charAt(0) || '?'
                                })
                            )
                        }}
                    />
                ) : (
                    <div className="poster-placeholder">
                        {rep.title?.charAt(0) || '?'}
                    </div>
                )}
                <div className="poster-status-bar" style={{ '--status-color': availableCount === series.length ? 'var(--success)' : 'var(--text-muted)' }}>
                    <span className="poster-status-label">{availableCount} / {series.length} Available</span>
                </div>
                {monitoredCount > 0 && (
                    <div className="poster-monitored-dot" title={`${monitoredCount} monitored`} />
                )}
            </div>

            <div className="poster-info">
                <div className="poster-title" title={rep.title}>{rep.title}</div>
                <div className="poster-meta">
                    <span>{series.length} Episodes</span>
                    {rep.language && (
                        <span className="poster-lang">{rep.language}</span>
                    )}
                </div>
            </div>
        </div>
    )
}

function SeriesModal({ series, onClose, onTrigger, onDelete, onToggleMonitor }) {
    const rep = series[0]
    const seasons = [...new Set(series.map(e => e.season_number))].sort((a, b) => a - b)
    const [selectedSeason, setSelectedSeason] = useState(seasons[0])

    const seasonEpisodes = series.filter(e => e.season_number === selectedSeason).sort((a, b) => a.episode_number - b.episode_number)

    return (
        <div className="modal-overlay" onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}>
            <div className="modal-content card" onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: 800, maxHeight: '90vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-secondary)', overflow: 'hidden' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px', borderBottom: '1px solid var(--border)' }}>
                    <h2 style={{ margin: 0 }}>{rep.title}</h2>
                    <button className="btn btn-secondary" onClick={onClose}>✕</button>
                </div>
                
                <div style={{ padding: '20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                        <span style={{ fontWeight: 'bold' }}>Season:</span>
                        <select 
                            className="form-input" 
                            value={selectedSeason} 
                            onChange={e => setSelectedSeason(Number(e.target.value))}
                            style={{ width: 120 }}
                        >
                            {seasons.map(s => <option key={s} value={s}>Season {s}</option>)}
                        </select>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => seasonEpisodes.forEach(ep => { if (!ep.monitored) onToggleMonitor(ep.id, ep.monitored) })}>
                            Monitor Season
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={() => seasonEpisodes.forEach(ep => { if (ep.status !== 'downloading' && ep.status !== 'importing') onTrigger(ep.id, ep.tmdb_id, ep.language, ep.media_type, ep.season_number, ep.episode_number) })}>
                            Download Season
                        </button>
                    </div>
                </div>

                <div style={{ overflowY: 'auto', padding: '20px', flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {seasonEpisodes.map(ep => {
                        const status = (ep.status || '').toLowerCase()
                        const colour = STATUS_COLOR[status] || 'var(--text-muted)'
                        const label = STATUS_LABEL[status] || status.toUpperCase()

                        return (
                            <div key={ep.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px' }}>
                                <div>
                                    <div style={{ fontWeight: 'bold', fontSize: 16 }}>Episode {ep.episode_number}</div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4 }}>
                                        <span style={{ fontSize: 12, color: colour, fontWeight: 'bold' }}>{label}</span>
                                        {ep.monitored ? <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>✓ Monitored</span> : <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>○ Unmonitored</span>}
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <button className="btn btn-secondary btn-sm" onClick={() => onToggleMonitor(ep.id, ep.monitored)}>
                                        {ep.monitored ? 'Unmonitor' : 'Monitor'}
                                    </button>
                                    <button className="btn btn-primary btn-sm" onClick={() => onTrigger(ep.id, ep.tmdb_id, ep.language, ep.media_type, ep.season_number, ep.episode_number)} disabled={status === 'downloading' || status === 'importing'}>
                                        Download
                                    </button>
                                    <button className="btn btn-danger btn-sm" onClick={() => onDelete(ep.id)}>✕</button>
                                </div>
                            </div>
                        )
                    })}
                </div>
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
    const [activeFilters, setActiveFilters] = useState(['all'])
    const [selectedSeriesId, setSelectedSeriesId] = useState(null)

    const fetchMovies = async () => {
        try {
            const res = await fetch('/api/jobs?limit=10000')
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
            await api.syncRadarrStatus()
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

    const triggerJob = async (id, tmdbId, lang, mediaType = 'movie', seasonNumber = null, episodeNumber = null) => {
        try {
            await fetch('/api/jobs/trigger', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    tmdb_id: tmdbId, 
                    language: lang,
                    media_type: mediaType,
                    season_number: seasonNumber,
                    episode_number: episodeNumber
                })
            })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const toggleFilter = (key) => {
        setActiveFilters(prev => {
            if (key === 'all') return ['all']
            const next = prev.filter(f => f !== 'all')
            if (next.includes(key)) {
                const updated = next.filter(f => f !== key)
                return updated.length === 0 ? ['all'] : updated
            } else {
                return [...next, key]
            }
        })
    }

    const typeMovies = movies.filter(m => (m.media_type || 'movie') === mediaType)

    // Apply Filters
    const filtered = typeMovies.filter(m => {
        const matchSearch = m.title.toLowerCase().includes(search.toLowerCase())
        const matchTab = matchesFilters(m, activeFilters)
        return matchSearch && matchTab
    })

    // Grouping for Series
    let groupedSeries = {}
    if (mediaType === 'series') {
        filtered.forEach(m => {
            if (!groupedSeries[m.tmdb_id]) groupedSeries[m.tmdb_id] = []
            groupedSeries[m.tmdb_id].push(m)
        })
    }

    const uniqueLangs = [...new Set(typeMovies.map(m => m.language).filter(Boolean))].sort()
    const dynamicTabs = [
        ...BASE_TABS,
        ...uniqueLangs.map(lang => ({ key: `lang_${lang}`, label: lang.charAt(0).toUpperCase() + lang.slice(1) }))
    ]

    const selectedSeriesEpisodes = selectedSeriesId && groupedSeries[selectedSeriesId] ? groupedSeries[selectedSeriesId] : null

    return (
        <div className="main-content">
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">{mediaType === 'series' ? 'Series' : 'Movies'}</h1>
                    <p className="page-subtitle">{mediaType === 'series' ? Object.keys(groupedSeries).length : typeMovies.length} tracked</p>
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

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
                <div className="filter-tabs" style={{ display: 'flex', flexWrap: 'wrap' }}>
                    {dynamicTabs.map(tab => {
                        const isActive = activeFilters.includes(tab.key)
                        return (
                            <button
                                key={tab.key}
                                className={`filter-tab${isActive ? ' active' : ''}`}
                                onClick={() => toggleFilter(tab.key)}
                            >
                                {tab.label}
                            </button>
                        )
                    })}
                </div>
                <input
                    className="filter-search"
                    placeholder={`Search ${mediaType === 'series' ? 'series' : 'movies'}...`}
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
            </div>

            {loading && movies.length === 0 ? (
                <div className="empty-state">
                    <div className="spinner" style={{ width: 28, height: 28, margin: '0 auto 16px' }} />
                    <div className="empty-state-text">Loading {mediaType === 'series' ? 'series' : 'movies'}...</div>
                </div>
            ) : filtered.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-state-icon" style={{ fontSize: 40 }}>{mediaType === 'series' ? '📺' : '🎬'}</div>
                    <div className="empty-state-text">No {mediaType === 'series' ? 'series' : 'movies'} found</div>
                </div>
            ) : (
                <div className="poster-grid">
                    {mediaType === 'series' 
                        ? Object.values(groupedSeries).map(series => (
                            <SeriesCard
                                key={series[0].tmdb_id}
                                series={series}
                                onClick={() => setSelectedSeriesId(series[0].tmdb_id)}
                            />
                        ))
                        : filtered.map(movie => (
                            <PosterCard
                                key={movie.id}
                                movie={movie}
                                onTrigger={triggerJob}
                                onDelete={deleteJob}
                                onToggleMonitor={toggleMonitor}
                            />
                        ))
                    }
                </div>
            )}

            {selectedSeriesEpisodes && (
                <SeriesModal 
                    series={selectedSeriesEpisodes} 
                    onClose={() => setSelectedSeriesId(null)}
                    onTrigger={triggerJob}
                    onDelete={deleteJob}
                    onToggleMonitor={toggleMonitor}
                />
            )}
        </div>
    )
}
