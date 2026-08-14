import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge, ProgressBar, timeAgo, formatBytes, formatETA, formatAirDate } from '../components/ui'
import TriggerModal from '../components/TriggerModal'

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
    discovered: 'var(--success)',
    not_in_radarr: 'var(--text-muted)',
}

const STATUS_LABEL = {
    done: 'Available',
    downloading: 'Downloading',
    searching: 'Searching',
    failed: 'Failed',
    not_found: 'Not Found',
    pending: 'Pending',
    checking_radarr: 'Checking Sonarr',
    importing: 'Importing',
    skipped: 'Skipped',
    movie_missing: 'Missing',
    discovered: 'Discovered',
    not_in_radarr: 'Deleted in Sonarr',
}

// Filter tabs definition
const TABS = [
    { key: 'all', label: 'All Jobs' },
    { key: 'active', label: 'Active' },
    { key: 'missing', label: 'Missing' },
    { key: 'discovered', label: 'Discovered' },
    { key: 'done', label: 'Done' },
    { key: 'failed', label: 'Failed' }
]

function matchesTab(movie, tab) {
    const s = (movie.status || '').toLowerCase()
    if (tab === 'all') return true
    if (tab === 'active') return ['downloading', 'searching', 'pending', 'checking_radarr', 'importing'].includes(s)
    if (tab === 'missing') return s === 'movie_missing' || s === 'not_found' || s === 'not_in_radarr'
    if (tab === 'discovered') return s === 'discovered'
    if (tab === 'done') return s === 'done'
    if (tab === 'failed') return s === 'failed'
    return true
}

function tabCount(movies, tab) {
    return movies.filter(m => matchesTab(m, tab)).length
}

function SeriesModal({ series, onClose, onTrigger, onDelete, onCancel, onToggleMonitor, onSync, settings, onImportUrl }) {
    const [importUrl, setImportUrl] = useState('')
    const [importLoading, setImportLoading] = useState(false)
    const [importMsg, setImportMsg] = useState('')
    const [importTargetJobId, setImportTargetJobId] = useState(null)

    if (!series) return null;

    // group episodes by season
    const seasons = {}
    series.episodes.forEach(e => {
        const s = e.season_number !== null ? e.season_number : 1
        if (!seasons[s]) seasons[s] = []
        seasons[s].push(e)
    })
    
    // Sort seasons
    const seasonKeys = Object.keys(seasons).map(Number).sort((a, b) => b - a)

    const handleImportUrl = async (jobId) => {
        if (!importUrl.trim()) return
        setImportTargetJobId(jobId)
        setImportLoading(true)
        setImportMsg('')
        try {
            await onImportUrl(jobId, importUrl.trim())
            setImportMsg('Download started!')
            setImportUrl('')
            setTimeout(() => setImportMsg(''), 3000)
        } catch (err) {
            setImportMsg(`Error: ${err.message}`)
        } finally {
            setImportLoading(false)
            setImportTargetJobId(null)
        }
    }

    return (
        <div className="modal-overlay" onClick={onClose} style={{position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <div className="modal-content card" onClick={e => e.stopPropagation()} style={{width: 700, maxWidth: '95%', maxHeight: '90vh', overflowY: 'auto', padding: 24, position: 'relative', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12}}>
                <button onClick={onClose} style={{position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-secondary)'}}>✕</button>
                <div style={{ display: 'flex', gap: 20, marginBottom: 24 }}>
                    {series.poster_path ? (
                        <img 
                            src={series.poster_path.startsWith('http') ? series.poster_path : `https://image.tmdb.org/t/p/w300${series.poster_path}`} 
                            style={{ width: 120, borderRadius: 8, objectFit: 'cover' }} 
                            alt={series.title} 
                        />
                    ) : (
                        <div style={{ width: 120, height: 180, background: 'var(--bg-tertiary)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>?</div>
                    )}
                    <div>
                        <h2 style={{marginTop: 0, marginBottom: 8}}>{series.title}</h2>
                        <div style={{color: 'var(--text-secondary)', marginBottom: 12}}>
                            {series.episodes.length} Episodes Tracked
                        </div>
                        <div style={{display: 'flex', gap: 10}}>
                            <button className="btn btn-secondary btn-sm" onClick={() => onSync(series.episodes[0]?.id)}>
                                ↻ Force Sync Sonarr
                            </button>
                            {settings?.tv_download_sources_priority?.includes('1tamilmv') && (
                                <a 
                                    className="btn btn-secondary btn-sm" 
                                    href={`https://www.1tamilmv.fi/index.php?/search/&q=${encodeURIComponent(series.title)}&search_and_or=and`}
                                    target="_blank" rel="noopener noreferrer"
                                >
                                    Search 1TamilMV
                                </a>
                            )}
                            {settings?.tv_download_sources_priority?.includes('bollyzone') && (
                                <a 
                                    className="btn btn-secondary btn-sm" 
                                    href={`https://www.bollyzone.to/?s=${encodeURIComponent(series.title)}`}
                                    target="_blank" rel="noopener noreferrer"
                                >
                                    Search BollyZone
                                </a>
                            )}
                            {settings?.tv_download_sources_priority?.includes('fmovies') && (
                                <a 
                                    className="btn btn-secondary btn-sm" 
                                    href={`${settings?.fmovies_base_url || 'https://www.f-movies.org'}/search/${encodeURIComponent(series.title)}`}
                                    target="_blank" rel="noopener noreferrer"
                                >
                                    Search FMovies
                                </a>
                            )}
                        </div>
                    </div>
                </div>
                
                {importMsg && (
                    <div style={{ marginBottom: 16, padding: 12, background: importMsg.includes('Error') ? 'var(--error-light)' : 'rgba(34,197,94,0.1)', color: importMsg.includes('Error') ? 'var(--error)' : 'var(--success)', borderRadius: 8 }}>
                        {importMsg}
                    </div>
                )}

                <div>
                    {seasonKeys.map(season => (
                        <details key={season} style={{ marginBottom: 16 }} open={seasonKeys.length === 1 || season === seasonKeys[0]}>
                            <summary style={{ fontSize: 18, fontWeight: 'bold', borderBottom: '1px solid var(--border)', paddingBottom: 8, marginBottom: 12, cursor: 'pointer' }}>
                                Season {season}
                            </summary>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingLeft: 8 }}>
                                {seasons[season].map(ep => {
                                    const isMissing = ep.status === 'movie_missing';
                                    let displayLabel = STATUS_LABEL[(ep.status || '').toLowerCase()] || ep.status;
                                    let displayColor = STATUS_COLOR[(ep.status || '').toLowerCase()] || 'var(--text-primary)';
                                    
                                    if (isMissing && ep.release_date) {
                                        const rDate = new Date(ep.release_date + 'Z');
                                        if (!isNaN(rDate) && rDate > new Date()) {
                                            displayLabel = 'Not Aired';
                                            displayColor = 'var(--text-muted)';
                                        }
                                    }
                                    
                                    return (
                                    <div key={ep.id} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, padding: 12, background: 'var(--bg-tertiary)', borderRadius: 8 }}>
                                        <div style={{ fontWeight: 'bold', minWidth: 40 }}>
                                            E{String(ep.episode_number).padStart(2, '0')}
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: 13, color: displayColor }}>
                                                {displayLabel}
                                            </div>
                                            {ep.status === 'downloading' && (
                                                <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                                                    <div style={{ flex: 1, height: 4, background: 'var(--bg-primary)', borderRadius: 2, overflow: 'hidden' }}>
                                                        <div style={{ height: '100%', width: `${ep.progress_pct}%`, background: '#3b82f6' }} />
                                                    </div>
                                                    <span>{ep.progress_pct}%</span>
                                                </div>
                                            )}
                                            {ep.file_path && (
                                                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={ep.file_path}>
                                                    {ep.file_path}
                                                </div>
                                            )}
                                        </div>
                                        
                                        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
                                            {ep.release_date && (
                                                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginRight: 4, textAlign: 'right' }}>
                                                    {formatAirDate(ep.release_date)}
                                                </div>
                                            )}
                                            {ep.status === 'movie_missing' && (
                                                <div style={{ display: 'flex', gap: 4, marginRight: 8 }}>
                                                    <input 
                                                        type="text" 
                                                        placeholder="Paste URL..." 
                                                        className="form-input" 
                                                        style={{ width: 120, padding: '4px 8px', fontSize: 11 }}
                                                        onChange={e => setImportUrl(e.target.value)}
                                                    />
                                                    <button 
                                                        className="btn btn-secondary btn-sm" 
                                                        style={{ padding: '4px 8px', fontSize: 11 }}
                                                        disabled={importLoading}
                                                        onClick={() => handleImportUrl(ep.id)}
                                                    >
                                                        {importLoading && importTargetJobId === ep.id ? '...' : 'Import'}
                                                    </button>
                                                </div>
                                            )}
                                            {ep.status === 'downloading' && (
                                                <button 
                                                    className="btn btn-danger btn-sm" 
                                                    style={{ padding: '4px 8px', fontSize: 11 }}
                                                    onClick={() => onCancel(ep.id)}
                                                >
                                                    Stop
                                                </button>
                                            )}
                                            <button 
                                                className="btn btn-primary btn-sm" 
                                                style={{ padding: '4px 8px', fontSize: 11 }}
                                                onClick={() => onTrigger(ep)}
                                                disabled={ep.status === 'downloading' || ep.status === 'importing'}
                                            >
                                                Trigger
                                            </button>
                                            <button 
                                                className="btn btn-danger btn-sm" 
                                                style={{ padding: '4px 8px', fontSize: 11 }}
                                                onClick={() => onDelete(ep.id)}
                                            >
                                                Del
                                            </button>
                                        </div>
                                    </div>
                                    )
                                })}
                            </div>
                        </details>
                    ))}
                </div>
            </div>
        </div>
    )
}

function PosterCard({ series, onSelect }) {
    const status = (series.status || '').toLowerCase()
    const colour = STATUS_COLOR[status] || 'var(--text-muted)'
    const label = STATUS_LABEL[status] || status.toUpperCase()

    const posterSrc = series.poster_path
        ? (series.poster_path.startsWith('http') ? series.poster_path : `https://image.tmdb.org/t/p/w300${series.poster_path}`)
        : null

    return (
        <div className="poster-card" onClick={onSelect} style={{cursor: 'pointer'}}>
            <div className="poster-img-wrap">
                {posterSrc ? (
                    <img
                        src={posterSrc}
                        alt={series.title}
                        className="poster-img"
                        onError={e => {
                            e.target.onerror = null
                            e.target.replaceWith(
                                Object.assign(document.createElement('div'), {
                                    className: 'poster-placeholder',
                                    textContent: series.title?.charAt(0) || '?'
                                })
                            )
                        }}
                    />
                ) : (
                    <div className="poster-placeholder">
                        {series.title?.charAt(0) || '?'}
                    </div>
                )}
                <div className="poster-status-bar" style={{ '--status-color': colour }}>
                    <span className="poster-status-label">{label}</span>
                    {status === 'downloading' && series.progress_pct > 0 && (
                        <div className="poster-progress-wrap">
                            <div
                                className="poster-progress-fill"
                                style={{ width: `${series.progress_pct}%` }}
                            />
                        </div>
                    )}
                </div>
                {/* Monitored / Missing indicator dot */}
                <div
                    className={`poster-monitored-dot${!series.monitored ? ' poster-monitored-dot--unmonitored' : ''}${status === 'movie_missing' ? ' poster-monitored-dot--missing' : ''}`}
                    title={series.monitored ? (status === 'movie_missing' ? 'File missing from Sonarr folder' : 'Monitored') : 'Unmonitored'}
                />
            </div>

            <div className="poster-info">
                <div className="poster-title" title={series.title}>
                    {series.title}
                </div>
                <div className="poster-meta">
                    <span className="poster-lang">{series.episodes.length} Episodes</span>
                </div>
            </div>
        </div>
    )
}

export default function Series() {
    const [movies, setMovies] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [isTriggering, setIsTriggering] = useState(false)
    const [search, setSearch] = useState('')
    const [searchParams, setSearchParams] = useSearchParams()
    const activeTab = searchParams.get('tab') || 'all'
    const setActiveTab = (tab) => {
        const p = new URLSearchParams(searchParams)
        p.set('tab', tab)
        setSearchParams(p)
    }
    const [selectedSeries, setSelectedSeries] = useState(null)
    const [settings, setSettings] = useState(null)
    const [showTriggerModal, setShowTriggerModal] = useState(false)

    const handleImportList = async () => {
        if (!confirm('This will import all monitored series from Sonarr. Continue?')) return
        setIsTriggering(true)
        try {
            const res = await api.importSonarr()
            alert(`Imported/updated ${res.imported} episodes successfully!`)
            fetchMovies()
        } catch (err) {
            alert(`Error: ${err.message}`)
        } finally {
            setIsTriggering(false)
        }
    }

    const fetchMovies = async () => {
        try {
            const res = await fetch('/api/jobs?media_type=tv')
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
        api.getSettings().then(setSettings).catch(() => {})
        const interval = setInterval(fetchMovies, 5000)
        return () => clearInterval(interval)
    }, [])

    const triggerMonitoredTV = async () => {
        setIsTriggering(true)
        try {
            await api.triggerMonitoredTV()
            fetchMovies()
        } catch (err) { console.error(err) }
        finally { setIsTriggering(false) }
    }

    const deleteJob = async (id) => {
        if (!confirm('Clear this episode?')) return
        try {
            await fetch(`/api/jobs/${id}`, { method: 'DELETE' })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const cancelJob = async (id) => {
        try {
            await api.cancelJob(id)
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const toggleMonitor = async (movie) => {
        try {
            await fetch(`/api/jobs/${movie.id}/monitor`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ monitored: !movie.monitored })
            })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const syncMovie = async (id) => {
        try {
            await api.syncAllSonarr() 
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const syncAllSonarr = async () => {
        setIsTriggering(true)
        try {
            await api.syncAllSonarr()
            fetchMovies()
        } catch (err) { console.error(err) }
        finally { setIsTriggering(false) }
    }
    
    const triggerJob = async (movie, indexer = null) => {
        if ((movie.status || '').toLowerCase() === 'discovered' && !indexer) {
            try {
                await fetch(`/api/jobs/${movie.id}/download`, { method: 'POST' })
                fetchMovies()
            } catch (err) { console.error(err) }
            return
        }
        
        try {
            await fetch('/api/jobs/trigger', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    media_type: 'tv',
                    tvdb_id: movie.tvdb_id,
                    season_number: movie.season_number,
                    episode_number: movie.episode_number,
                    indexer
                })
            })
            fetchMovies()
        } catch (err) { console.error(err) }
    }

    const handleImportUrl = async (jobId, url) => {
        await api.importUrl(jobId, url)
        fetchMovies()
    }

    // Grouping Logic
    const groupedSeries = {}
    movies.forEach(m => {
        const matchSearch = m.title.toLowerCase().includes(search.toLowerCase())
        if (search && !matchSearch) return; // filter by search first

        const seriesKey = m.tvdb_id ? String(m.tvdb_id) : m.title.split(/ S\d{2}E\d{2}/)[0].trim()
        if (!groupedSeries[seriesKey]) {
            groupedSeries[seriesKey] = {
                id: seriesKey,
                tvdb_id: m.tvdb_id,
                title: m.title.split(/ S\d{2}E\d{2}/)[0].trim(),
                poster_path: m.poster_path,
                language: m.language,
                episodes: [],
            }
        }
        groupedSeries[seriesKey].episodes.push(m)
    })

    const seriesList = Object.values(groupedSeries).map(s => {
        s.episodes.sort((a, b) => {
            if (a.season_number !== b.season_number) return (a.season_number || 1) - (b.season_number || 1);
            return (a.episode_number || 1) - (b.episode_number || 1);
        })
        
        const hasDownloading = s.episodes.some(e => e.status === 'downloading')
        const hasMissing = s.episodes.some(e => e.status === 'movie_missing')
        const hasSearching = s.episodes.some(e => e.status === 'searching')
        
        s.status = hasDownloading ? 'downloading' : (hasSearching ? 'searching' : (hasMissing ? 'movie_missing' : s.episodes[0].status))
        s.monitored = s.episodes.some(e => e.monitored)
        s.progress_pct = hasDownloading ? Math.max(...s.episodes.map(e => e.progress_pct || 0)) : 0
        return s;
    }).filter(s => matchesTab(s, activeTab)) // apply tab filter on the series level

    return (
        <div className="main-content">
            {selectedSeries && (
                <SeriesModal 
                    series={seriesList.find(s => s.id === selectedSeries.id) || selectedSeries} 
                    onClose={() => setSelectedSeries(null)} 
                    onTrigger={triggerJob} 
                    onDelete={deleteJob}
                    onCancel={cancelJob}
                    onToggleMonitor={toggleMonitor}
                    onSync={syncMovie} 
                    settings={settings} 
                    onImportUrl={handleImportUrl} 
                />
            )}
            {showTriggerModal && <TriggerModal onClose={() => setShowTriggerModal(false)} onSuccess={fetchMovies} />}
            
            {/* Header */}
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">Series Library</h1>
                    <p className="page-subtitle">{seriesList.length} tracked series</p>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                    <button className="btn btn-secondary" onClick={handleImportList} disabled={isTriggering}>
                        Import List
                    </button>
                    <button className="btn btn-secondary" onClick={syncAllSonarr} disabled={isTriggering}>
                        {isTriggering ? 'Syncing...' : '↻ Sync Sonarr'}
                    </button>
                    <button className="btn btn-primary" onClick={triggerMonitoredTV} disabled={isTriggering || movies.length === 0}>
                        {isTriggering ? 'Triggering...' : 'Trigger Monitored'}
                    </button>
                    <button className="btn btn-primary" onClick={() => setShowTriggerModal(true)}>
                        ＋ Trigger Download
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
                <div className="filter-tabs">
                    {TABS.map(tab => {
                        const count = Object.values(groupedSeries).map(s => {
                            const hasDownloading = s.episodes.some(e => e.status === 'downloading')
                            const hasMissing = s.episodes.some(e => e.status === 'movie_missing')
                            const hasSearching = s.episodes.some(e => e.status === 'searching')
                            s.status = hasDownloading ? 'downloading' : (hasSearching ? 'searching' : (hasMissing ? 'movie_missing' : s.episodes[0].status))
                            return s
                        }).filter(s => matchesTab(s, tab.key)).length
                        
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
                <input
                    className="filter-search"
                    placeholder="Search series..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
            </div>

            {/* Poster grid */}
            {loading && movies.length === 0 ? (
                <div className="empty-state">
                    <div className="spinner" style={{ width: 28, height: 28, margin: '0 auto 16px' }} />
                    <div className="empty-state-text">Loading series...</div>
                </div>
            ) : seriesList.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-state-icon" style={{ fontSize: 40 }}>🎬</div>
                    <div className="empty-state-text">No series found</div>
                </div>
            ) : (
                <div className="poster-grid">
                    {seriesList.map(series => (
                        <PosterCard
                            key={series.id}
                            series={series}
                            onSelect={() => setSelectedSeries(series)}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
