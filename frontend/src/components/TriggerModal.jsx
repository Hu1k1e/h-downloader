import { useState } from 'react'
import { api } from '../api'

export default function TriggerModal({ onClose, onSuccess }) {
    const [tmdbId, setTmdbId] = useState('')
    const [title, setTitle] = useState('')
    const [language, setLanguage] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    const LANGUAGES = ['malayalam', 'tamil', 'telugu', 'hindi', 'kannada', 'bengali', 'marathi', 'punjabi']

    async function handleSubmit(e) {
        e.preventDefault()
        setError('')
        if (!tmdbId && !title) {
            setError('Provide a TMDB ID or Movie Title')
            return
        }
        setLoading(true)
        try {
            await api.triggerDownload({
                tmdb_id: tmdbId ? parseInt(tmdbId) : null,
                title: title || null,
                language: language || null,
            })
            onSuccess?.()
            onClose()
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
            <div className="modal">
                <div className="modal-title">🎬 Trigger Manual Download</div>
                <form onSubmit={handleSubmit}>
                    <div style={{ marginBottom: 14 }}>
                        <div className="form-label" style={{ marginBottom: 6 }}>TMDB ID</div>
                        <input
                            className="form-input"
                            type="number"
                            placeholder="e.g. 123456"
                            value={tmdbId}
                            onChange={e => setTmdbId(e.target.value)}
                        />
                    </div>
                    <div style={{ textAlign: 'center', color: 'var(--text-muted)', margin: '8px 0', fontSize: 12 }}>— or —</div>
                    <div style={{ marginBottom: 14 }}>
                        <div className="form-label" style={{ marginBottom: 6 }}>Movie Title</div>
                        <input
                            className="form-input"
                            type="text"
                            placeholder="e.g. Marco"
                            value={title}
                            onChange={e => setTitle(e.target.value)}
                        />
                    </div>
                    <div style={{ marginBottom: 14 }}>
                        <div className="form-label" style={{ marginBottom: 6 }}>Language (optional)</div>
                        <select className="form-select" value={language} onChange={e => setLanguage(e.target.value)}>
                            <option value="">Auto-detect</option>
                            {LANGUAGES.map(l => (
                                <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
                            ))}
                        </select>
                    </div>

                    {error && (
                        <div style={{ background: 'var(--error-light)', color: 'var(--error)', borderRadius: 6, padding: '8px 12px', fontSize: 13, marginBottom: 12 }}>
                            {error}
                        </div>
                    )}

                    <div className="modal-actions">
                        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? <><span className="spinner" /> Searching…</> : '🔍 Search & Download'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}
