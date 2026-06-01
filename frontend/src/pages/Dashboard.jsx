import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'
import { StatusBadge, ProgressBar, formatBytes, timeAgo } from '../components/ui'
import TriggerModal from '../components/TriggerModal'

export default function Dashboard() {
    const [stats, setStats] = useState(null)
    const [jobs, setJobs] = useState([])
    const [showModal, setShowModal] = useState(false)

    const load = useCallback(async () => {
        try {
            const [s, j] = await Promise.all([
                api.getStats(),
                api.getJobs({ limit: 50 }),
            ])
            setStats(s)
            setJobs(j)
        } catch { }
    }, [])

    useEffect(() => {
        load()
        const t = setInterval(load, 5000)
        return () => clearInterval(t)
    }, [load])

    const active = jobs.filter(j => ['downloading', 'searching', 'checking_radarr', 'importing'].includes(j.status))
    const recent = jobs.slice(0, 8)

    return (
        <div className="main-content">
            <div className="page-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h1 className="page-title">Dashboard</h1>
                    <p className="page-subtitle">Monitor and manage your downloads</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowModal(true)}>
                    ＋ Trigger Download
                </button>
            </div>

            {/* Stats */}
            <div className="stats-grid">
                <div className="stat-card">
                    <div className="stat-label">Total Jobs</div>
                    <div className="stat-value">{stats?.total ?? '—'}</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Active Downloads</div>
                    <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={stats?.active > 0 ? { color: 'var(--accent)' } : {}}>
                            {stats?.active ?? '—'}
                        </span>
                        {stats?.active > 0 && <span className="stat-dot" />}
                    </div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Completed</div>
                    <div className={`stat-value${stats?.completed > 0 ? ' green' : ''}`}>
                        {stats?.completed ?? '—'}
                    </div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Failed</div>
                    <div className={`stat-value${stats?.failed > 0 ? ' red' : ''}`}>
                        {stats?.failed ?? '—'}
                    </div>
                </div>
            </div>

            {/* Active downloads */}
            <div className="section-title">Active Downloads</div>
            <div className="download-list">
                {active.length === 0 ? (
                    <div className="card" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>
                        No active downloads
                    </div>
                ) : (
                    active.map(job => (
                        <div className="download-card" key={job.id}>
                            <div className="download-card-top">
                                <div>
                                    <div className="download-movie-title">{job.title}</div>
                                    <div className="download-meta" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
                                        {job.year && <span>{job.year}</span>}
                                        {job.language && (
                                            <span className="poster-lang">
                                                {job.language.charAt(0).toUpperCase() + job.language.slice(1)}
                                            </span>
                                        )}
                                        {job.einthusan_url && (
                                            <span style={{ color: 'var(--text-muted)' }}>· via Search</span>
                                        )}
                                    </div>
                                </div>
                                <div className="download-card-right">
                                    <StatusBadge status={job.status} />
                                </div>
                            </div>
                            <ProgressBar pct={job.progress_pct} />
                            <div className="download-stats-row">
                                <span>{job.progress_pct ?? 0}%</span>
                                {job.total_bytes > 0 && (
                                    <span>{formatBytes(job.downloaded_bytes)} / {formatBytes(job.total_bytes)}</span>
                                )}
                                <span style={{ marginLeft: 'auto' }}>{timeAgo(job.updated_at)}</span>
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* Recent activity */}
            <div className="section-title">Recent Activity</div>
            <div className="card">
                {recent.length === 0 ? (
                    <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '20px' }}>
                        No jobs yet — trigger a download to get started!
                    </div>
                ) : (
                    <div className="activity-log">
                        {recent.map(job => {
                            const dotClass =
                                job.status === 'done' ? 'green' :
                                    (job.status === 'failed' || job.status === 'movie_missing') ? 'red' :
                                        (job.status === 'searching' || job.status === 'downloading') ? 'amber' : ''
                            return (
                                <div className="activity-item" key={job.id}>
                                    <span className="activity-time">{timeAgo(job.updated_at)}</span>
                                    <span className={`activity-dot ${dotClass}`} />
                                    <span style={{ fontWeight: 500, color: 'var(--text-primary)', flex: 1 }}>{job.title}</span>
                                    <StatusBadge status={job.status} />
                                    {job.error_msg && (
                                        <span style={{ color: 'var(--error)', fontSize: 11 }} title={job.error_msg}>
                                            ⚠ {job.error_msg.slice(0, 50)}
                                        </span>
                                    )}
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>

            {showModal && (
                <TriggerModal onClose={() => setShowModal(false)} onSuccess={load} />
            )}
        </div>
    )
}
