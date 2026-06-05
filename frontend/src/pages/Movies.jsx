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
    pending: 'Pending',
    checking_radarr: 'Checking Radarr',
    importing: 'Importing',
    skipped: 'Skipped',
    movie_missing: 'File Missing',
}

// Filter tabs definition
const TABS = [
    { key: 'all', label: 'All' },
    { key: 'available', label: 'Available' },
    { key: 'radarr', label: 'Pending / Checking' },
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
    return true
}

function tabCount(movies, tab) {
    return movies.filter(m => matchesTab(m, tab)).length
}

function MovieModal({ movie, onClose }) {
    if (!movie) return null;
    return (
        <div className="modal-overlay" onClick={onClose} style={{position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <div className="modal-content card" onClick={e => e.stopPropagation()} style={{width: 500, maxWidth: '90%', maxHeight: '90vh', overflowY: 'auto', padding: 24, position: 'relative', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12}}>
                <button onClick={onClose} style={{position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-secondary)'}}>✕</button>
                <h2 style={{marginTop: 0, marginBottom: 8}}>{movie.title} {movie.year && `(${movie.year})`}</h2>
                <div style={{color: 'var(--text-secondary)', marginBottom: 24}}>{movie.language}</div>
                
                <div style={{marginBottom: 16}}>
                    <strong>Status:</strong> {STATUS_LABEL[(movie.status || '').toLowerCase()] || movie.status}
                </div>
                {movie.status === 'downloading' && (
                    <div style={{marginBottom: 16}}>
                        <strong>Progress:</strong> {movie.progress_pct}%
                        <div style={{height: 8, background: 'var(--bg-tertiary)', borderRadius: 4, marginTop: 4, overflow: 'hidden'}}>
                            <div style={{height: '100%', width: `${movie.progress_pct}%`, background: '#3b82f6'}} />
                        </div>
                    </div>
                )}
                {movie.source_indexer && (
                    <div style={{marginBottom: 16}}>
                        <strong>Source:</strong> {movie.source_indexer === '1tamilmv' ? '1TamilMV' : movie.source_indexer === 'einthusan' ? 'Einthusan' : movie.source_indexer}
                    </div>
                )}
                {movie.file_path && (
                    <div style={{marginBottom: 16}}>
                        <strong>Path:</strong> <span style={{fontFamily: 'monospace', fontSize: 13, wordBreak: 'break-all', display: 'block', marginTop: 4}}>{movie.file_path}</span>
                    </div>
                )}
                {movie.error_msg && (
                    <div style={{marginBottom: 16, color: 'var(--error)'}}>
                        <strong>Error:</strong> {movie.error_msg}
                    </div>
                )}
                <div style={{marginBottom: 16}}>
                    <strong>Added:</strong> {new Date(movie.created_at).toLocaleString()}
                </div>
                <div style={{marginBottom: 16}}>
                    <strong>Last Updated:</strong> {new Date(movie.updated_at).toLocaleString()}
                </div>
            </div>
        </div>
    )
}

function PosterCard({ movie, onTrigger, onDelete, onToggleMonitor, onSelect }) {
    const status = (movie.status || '').toLowerCase()
    const colour = STATUS_COLOR[status] || 'var(--text-muted)'
    const label = STATUS_LABEL[status] || status.toUpperCase()

    const posterSrc = movie.poster_path
        ? `https://image.tmdb.org/t/p/w300${movie.poster_path}`
        : null

    return (
        <div className="poster-card" onClick={() => onSelect(movie)} style={{cursor: 'pointer'}}>
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
                    {movie.year && <span>{movie.year}</span>}
                    {movie.language && (
                        <span className="poster-lang">{movie.language}</span>
                    )}
                </div>
            </div>

            <div className="poster-actions" onClick={e => e.stopPropagation()}>
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
                    title="Force search"
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

export default function Movies() {
    const [movies, setMovies] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [isTriggering, setIsTriggering] = useState(false)
    const [isSyncing, setIsSyncing] = useState(false)
    const [search, setSearch] = useState('')
    const [activeTab, setActiveTab] = useState('all')
    const [selectedMovie, setSelectedMovie] = useState(null)

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

    const filtered = movies.filter(m => {
        const matchSearch = m.title.toLowerCase().includes(search.toLowerCase())
        const matchTab = matchesTab(m, activeTab)
        return matchSearch && matchTab
    })

    return (
        <div className="main-content">
            {selectedMovie && <MovieModal movie={movies.find(m => m.id === selectedMovie.id) || selectedMovie} onClose={() => setSelectedMovie(null)} />}
            
            {/* Header */}
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">Movies</h1>
                    <p className="page-subtitle">{movies.length} tracked · {movies.filter(m => m.monitored).length} monitored</p>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-primary" onClick={triggerMissing} disabled={isTriggering || movies.length === 0}>
                        {isTriggering ? 'Triggering...' : 'Trigger Missing'}
                    </button>
                    <button className="btn btn-primary" onClick={triggerMonitored} disabled={isTriggering || movies.length === 0}>
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
                <div className="filter-tabs">
                    {TABS.map(tab => {
                        const count = tabCount(movies, tab.key)
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
                    placeholder="Search movies..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
            </div>

            {/* Poster grid */}
            {loading && movies.length === 0 ? (
                <div className="empty-state">
                    <div className="spinner" style={{ width: 28, height: 28, margin: '0 auto 16px' }} />
                    <div className="empty-state-text">Loading movies...</div>
                </div>
            ) : filtered.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-state-icon" style={{ fontSize: 40 }}>🎬</div>
                    <div className="empty-state-text">No movies found</div>
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
                            onSelect={setSelectedMovie}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
