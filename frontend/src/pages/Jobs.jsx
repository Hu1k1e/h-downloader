import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'
import { StatusBadge, ProgressBar, formatBytes, timeAgo } from '../components/ui'
import TriggerModal from '../components/TriggerModal'

const ALL_LANGS = ['malayalam', 'tamil', 'telugu', 'hindi', 'kannada', 'bengali', 'marathi', 'punjabi']

export default function Jobs() {
    const [jobs, setJobs] = useState([])
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')
    const [langFilter, setLangFilter] = useState('')
    const [showModal, setShowModal] = useState(false)
    const [loading, setLoading] = useState(true)

    const load = useCallback(async () => {
        try {
            const params = {}
            if (statusFilter) params.status = statusFilter
            if (langFilter) params.language = langFilter
            const data = await api.getJobs({ ...params, limit: 200 })
            setJobs(data)
        } catch { } finally {
            setLoading(false)
        }
    }, [statusFilter, langFilter])

    useEffect(() => {
        load()
        const t = setInterval(load, 5000)
        return () => clearInterval(t)
    }, [load])

    async function handleDelete(id) {
        if (!confirm('Remove this job?')) return
        await api.deleteJob(id)
        load()
    }

    async function handleRetry(id) {
        await api.retryJob(id)
        load()
    }

    const filtered = jobs.filter(j =>
        !search || j.title.toLowerCase().includes(search.toLowerCase())
    )

    return (
        <div className="main-content">
            <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <div>
                    <h1 className="page-title">Jobs</h1>
                    <p className="page-subtitle">All download jobs history</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowModal(true)}>
                    ＋ Trigger Download
                </button>
            </div>

            {/* Filters */}
            <div className="filter-bar">
                <input
                    type="text"
                    placeholder="Search by title…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
                <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                    <option value="">All Statuses</option>
                    <option value="downloading">Downloading</option>
                    <option value="searching">Searching</option>
                    <option value="done">Done</option>
                    <option value="failed">Failed</option>
                    <option value="not_found">Not Found</option>
                    <option value="pending">Pending</option>
                    <option value="skipped">Skipped</option>
                </select>
                <select value={langFilter} onChange={e => setLangFilter(e.target.value)}>
                    <option value="">All Languages</option>
                    {ALL_LANGS.map(l => <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>)}
                </select>
                <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 'auto' }}>
                    {filtered.length} jobs
                </span>
            </div>

            {/* Table */}
            <div className="table-wrap">
                {loading ? (
                    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-secondary)' }}>
                        <span className="spinner" /> &nbsp;Loading…
                    </div>
                ) : filtered.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">🎬</div>
                        <div className="empty-state-text">No jobs found</div>
                        <div className="empty-state-sub">Trigger a download to get started</div>
                    </div>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Movie Title</th>
                                <th>Language</th>
                                <th>Year</th>
                                <th>Status</th>
                                <th>Progress</th>
                                <th>Size</th>
                                <th>Path</th>
                                <th>Added</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map(job => (
                                <tr key={job.id}>
                                    <td style={{ color: 'var(--text-muted)' }}>{job.id}</td>
                                    <td>
                                        <div style={{ fontWeight: 500 }}>{job.title}</div>
                                        {job.error_msg && (
                                            <div style={{ fontSize: 11, color: 'var(--error)', marginTop: 2 }}
                                                title={job.error_msg}>
                                                ⚠ {job.error_msg.slice(0, 60)}{job.error_msg.length > 60 ? '…' : ''}
                                            </div>
                                        )}
                                    </td>
                                    <td>
                                        {job.language ? (
                                            <span style={{ textTransform: 'capitalize' }}>{job.language}</span>
                                        ) : '—'}
                                    </td>
                                    <td>{job.year || '—'}</td>
                                    <td><StatusBadge status={job.status} /></td>
                                    <td>
                                        <div className="progress-cell">
                                            {job.status === 'downloading' ? (
                                                <>
                                                    <ProgressBar pct={job.progress_pct} style={{ flex: 1, marginBottom: 0 }} />
                                                    <span style={{ fontSize: 11, color: 'var(--text-secondary)', minWidth: 30 }}>{job.progress_pct}%</span>
                                                </>
                                            ) : job.status === 'done' ? (
                                                <span style={{ color: 'var(--success)' }}>100%</span>
                                            ) : (
                                                <span style={{ color: 'var(--text-muted)' }}>—</span>
                                            )}
                                        </div>
                                    </td>
                                    <td style={{ color: 'var(--text-secondary)' }}>
                                        {job.total_bytes > 0 ? formatBytes(job.total_bytes) : '—'}
                                    </td>
                                    <td style={{ color: 'var(--text-muted)', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={job.file_path}>
                                        {job.file_path ? job.file_path.split(/[\/\\]/).pop() : '—'}
                                    </td>
                                    <td style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                        {timeAgo(job.created_at)}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: 4 }}>
                                            {['failed', 'not_found', 'skipped', 'done', 'movie_missing'].includes(job.status) && (
                                                <button className="btn btn-ghost btn-sm" onClick={() => handleRetry(job.id)} title="Retry">↺</button>
                                            )}
                                            <button className="btn btn-danger btn-sm" onClick={() => handleDelete(job.id)} title="Delete">✕</button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {showModal && <TriggerModal onClose={() => setShowModal(false)} onSuccess={load} />}
        </div>
    )
}
