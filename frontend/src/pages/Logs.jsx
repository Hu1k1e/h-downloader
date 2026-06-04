import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Logs() {
    const [logs, setLogs] = useState([])
    const [loading, setLoading] = useState(true)
    const [filterLevel, setFilterLevel] = useState('')
    const [searchQuery, setSearchQuery] = useState('')

    const loadLogs = async () => {
        setLoading(true)
        try {
            const data = await api.getLogs({ level: filterLevel, search: searchQuery })
            setLogs(data)
        } catch (e) {
            console.error(e)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        const t = setTimeout(() => {
            loadLogs()
        }, 300)
        return () => clearTimeout(t)
    }, [filterLevel, searchQuery])
    
    // Auto refresh logs every 10 seconds
    useEffect(() => {
        const interval = setInterval(() => {
            if (!searchQuery) { // Don't interrupt searching with jumps
                loadLogs()
            }
        }, 10000)
        return () => clearInterval(interval)
    }, [filterLevel, searchQuery])

    const handleDeleteAll = async () => {
        if (!window.confirm("Are you sure you want to delete ALL logs?")) return
        try {
            await api.deleteAllLogs()
            loadLogs()
        } catch (e) {
            alert(`Failed to delete logs: ${e.message}`)
        }
    }

    const handleDeleteOlderThan = async (days) => {
        if (!window.confirm(`Are you sure you want to delete logs older than ${days} days?`)) return
        try {
            await api.deleteLogsOlderThan(days)
            loadLogs()
        } catch (e) {
            alert(`Failed to delete logs: ${e.message}`)
        }
    }

    const formatTime = (isoString) => {
        const d = new Date(isoString)
        return d.toLocaleString()
    }

    const getLevelColor = (level) => {
        switch(level) {
            case 'info': return 'var(--info)'
            case 'warning': return 'var(--warning)'
            case 'error': return 'var(--error)'
            case 'debug': return 'var(--text-muted)'
            default: return 'var(--text-primary)'
        }
    }

    return (
        <div className="main-content">
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">System Logs</h1>
                    <p className="page-subtitle">View background task logs and orchestrator actions</p>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => handleDeleteOlderThan(7)}>Delete &gt; 7 Days</button>
                    <button className="btn btn-danger btn-sm" onClick={handleDeleteAll}>Delete All</button>
                </div>
            </div>

            <div className="card" style={{ marginBottom: 24, padding: '16px 20px' }}>
                <div className="filter-bar" style={{ marginBottom: 0 }}>
                    <div style={{ position: 'relative', flex: 1, maxWidth: 300 }}>
                        <span style={{ position: 'absolute', left: 12, top: 10, color: 'var(--text-muted)' }}>🔍</span>
                        <input
                            type="text"
                            placeholder="Search logs..."
                            style={{ paddingLeft: 36, width: '100%' }}
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                        />
                    </div>
                    <select value={filterLevel} onChange={e => setFilterLevel(e.target.value)}>
                        <option value="">All Levels</option>
                        <option value="info">Info</option>
                        <option value="warning">Warning</option>
                        <option value="error">Error</option>
                        <option value="debug">Debug</option>
                    </select>
                    <button className="btn btn-secondary" onClick={loadLogs} title="Refresh">
                        ↻
                    </button>
                </div>
            </div>

            <div className="table-wrap">
                {loading && logs.length === 0 ? (
                    <div className="empty-state">
                        <div className="spinner" style={{ marginBottom: 16 }}></div>
                        <div>Loading logs...</div>
                    </div>
                ) : logs.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">📝</div>
                        <div className="empty-state-text">No logs found</div>
                        <div className="empty-state-sub">Adjust your filters or search query</div>
                    </div>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th style={{ width: '180px' }}>Timestamp</th>
                                <th style={{ width: '100px' }}>Level</th>
                                <th style={{ width: '150px' }}>Action</th>
                                <th>Message</th>
                            </tr>
                        </thead>
                        <tbody>
                            {logs.map(log => (
                                <tr key={log.id}>
                                    <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{formatTime(log.timestamp)}</td>
                                    <td>
                                        <span style={{ 
                                            color: getLevelColor(log.level), 
                                            fontWeight: 600,
                                            textTransform: 'uppercase',
                                            fontSize: 11
                                        }}>
                                            {log.level}
                                        </span>
                                    </td>
                                    <td style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{log.action}</td>
                                    <td style={{ color: 'var(--text-secondary)' }}>
                                        {log.message}
                                        {log.tmdb_id && <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)', background: 'var(--bg-primary)', padding: '2px 6px', borderRadius: 4 }}>TMDB: {log.tmdb_id}</span>}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}
