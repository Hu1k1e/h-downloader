import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'

export default function Logs() {
    const [logs, setLogs] = useState([])
    const [loading, setLoading] = useState(true)
    const [level, setLevel] = useState('')
    const [search, setSearch] = useState('')
    const [olderThan, setOlderThan] = useState('')

    const fetchLogs = useCallback(async () => {
        setLoading(true)
        try {
            const data = await api.getLogs({ level, search })
            setLogs(data)
        } catch (e) {
            console.error('Failed to fetch logs:', e)
        } finally {
            setLoading(false)
        }
    }, [level, search])

    useEffect(() => {
        fetchLogs()
        const t = setInterval(fetchLogs, 15000)
        return () => clearInterval(t)
    }, [fetchLogs])

    const handleDelete = async () => {
        if (!confirm('Are you sure you want to delete these logs?')) return
        try {
            await api.deleteLogs(olderThan === 'all' ? null : olderThan)
            fetchLogs()
        } catch (e) {
            alert('Failed to delete logs')
        }
    }

    const getLevelClass = (lvl) => {
        switch (lvl) {
            case 'error': return 'log-level-error'
            case 'warning': return 'log-level-warning'
            case 'info': return 'log-level-info'
            case 'debug': return 'log-level-debug'
            default: return ''
        }
    }

    const getLevelColor = (lvl) => {
        switch (lvl) {
            case 'error': return 'var(--error)'
            case 'warning': return 'var(--warning)'
            case 'info': return 'var(--primary)'
            default: return 'var(--text-secondary)'
        }
    }

    return (
        <div className="main-content">
            <div className="page-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h1 className="page-title">System Logs</h1>
                    <p className="page-subtitle">View detailed actions and background task history</p>
                </div>
                
                <div style={{ display: 'flex', gap: '8px' }}>
                    <select className="input" value={olderThan} onChange={e => setOlderThan(e.target.value)} style={{ width: 'auto' }}>
                        <option value="">Select deletion...</option>
                        <option value="7">Older than 7 days</option>
                        <option value="30">Older than 30 days</option>
                        <option value="all">Delete All</option>
                    </select>
                    <button className="btn btn-secondary" onClick={handleDelete} disabled={!olderThan} style={{ color: 'var(--error)' }}>
                        Delete Logs
                    </button>
                </div>
            </div>

            <div className="card" style={{ marginBottom: '20px', padding: '16px', display: 'flex', gap: '16px' }}>
                <input 
                    type="text" 
                    className="input" 
                    placeholder="Search logs by action or message..." 
                    value={search} 
                    onChange={e => setSearch(e.target.value)}
                    style={{ flex: 1 }}
                />
                <select className="input" value={level} onChange={e => setLevel(e.target.value)} style={{ width: '200px' }}>
                    <option value="">All Levels</option>
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="error">Error</option>
                    <option value="debug">Debug</option>
                </select>
            </div>

            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <table className="table">
                    <thead>
                        <tr>
                            <th style={{ width: '160px' }}>Timestamp</th>
                            <th style={{ width: '80px' }}>Level</th>
                            <th style={{ width: '180px' }}>Action</th>
                            <th>Message</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && logs.length === 0 ? (
                            <tr>
                                <td colSpan="4" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>Loading logs...</td>
                            </tr>
                        ) : logs.length === 0 ? (
                            <tr>
                                <td colSpan="4" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>No logs found</td>
                            </tr>
                        ) : (
                            logs.map(log => (
                                <tr key={log.id}>
                                    <td style={{ whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>
                                        {new Date(log.timestamp + 'Z').toLocaleString()}
                                    </td>
                                    <td>
                                        <span style={{ 
                                            padding: '2px 6px', 
                                            borderRadius: '4px',
                                            fontSize: '11px',
                                            fontWeight: 'bold',
                                            textTransform: 'uppercase',
                                            color: getLevelColor(log.level),
                                            backgroundColor: getLevelColor(log.level) + '20'
                                        }}>
                                            {log.level}
                                        </span>
                                    </td>
                                    <td style={{ fontFamily: 'monospace', fontSize: '13px' }}>
                                        {log.action}
                                    </td>
                                    <td>{log.message}</td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
