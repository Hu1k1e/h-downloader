import { useState } from 'react'
import { api } from '../api'

export default function TriggerModal({ onClose, onSuccess }) {
    const [mediaType, setMediaType] = useState('movie')
    const [idInput, setIdInput] = useState('')
    const [title, setTitle] = useState('')
    const [language, setLanguage] = useState('')
    
    const [season, setSeason] = useState('')
    const [episode, setEpisode] = useState('')
    const [fullSeason, setFullSeason] = useState(false)
    
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    const LANGUAGES = ['malayalam', 'tamil', 'telugu', 'hindi', 'kannada', 'bengali', 'marathi', 'punjabi']

    async function handleSubmit(e) {
        e.preventDefault()
        setError('')
        if (!idInput && !title) {
            setError('Provide an ID or Title')
            return
        }
        
        if (mediaType === 'tv') {
            if (!season) {
                setError('Season number is required for TV Shows')
                return
            }
            if (!fullSeason && !episode) {
                setError('Episode number is required if not downloading full season')
                return
            }
        }
        
        setLoading(true)
        try {
            await api.triggerDownload({
                media_type: mediaType,
                tmdb_id: mediaType === 'movie' && idInput ? parseInt(idInput) : null,
                tvdb_id: mediaType === 'tv' && idInput ? parseInt(idInput) : null,
                title: title || null,
                language: mediaType === 'movie' ? (language || null) : null,
                season_number: mediaType === 'tv' ? parseInt(season) : null,
                episode_number: mediaType === 'tv' && !fullSeason ? parseInt(episode) : null
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
                    <div style={{ display: 'flex', gap: 16, marginBottom: 14 }}>
                        <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', background: mediaType === 'movie' ? 'var(--bg-tertiary)' : 'transparent', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}>
                            <input type="radio" checked={mediaType === 'movie'} onChange={() => setMediaType('movie')} />
                            Movie
                        </label>
                        <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', background: mediaType === 'tv' ? 'var(--bg-tertiary)' : 'transparent', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}>
                            <input type="radio" checked={mediaType === 'tv'} onChange={() => setMediaType('tv')} />
                            TV Show
                        </label>
                    </div>

                    <div style={{ marginBottom: 14 }}>
                        <div className="form-label" style={{ marginBottom: 6 }}>{mediaType === 'movie' ? 'TMDB ID' : 'TVDB ID'}</div>
                        <input
                            className="form-input"
                            type="number"
                            placeholder="e.g. 123456"
                            value={idInput}
                            onChange={e => setIdInput(e.target.value)}
                        />
                    </div>
                    <div style={{ textAlign: 'center', color: 'var(--text-muted)', margin: '8px 0', fontSize: 12 }}>— or —</div>
                    <div style={{ marginBottom: 14 }}>
                        <div className="form-label" style={{ marginBottom: 6 }}>{mediaType === 'movie' ? 'Movie Title' : 'TV Show Title'}</div>
                        <input
                            className="form-input"
                            type="text"
                            placeholder={mediaType === 'movie' ? 'e.g. Marco' : 'e.g. Khatron Ke Khiladi'}
                            value={title}
                            onChange={e => setTitle(e.target.value)}
                        />
                    </div>
                    
                    {mediaType === 'movie' && (
                        <div style={{ marginBottom: 14 }}>
                            <div className="form-label" style={{ marginBottom: 6 }}>Language (optional)</div>
                            <select className="form-select" value={language} onChange={e => setLanguage(e.target.value)}>
                                <option value="">Auto-detect</option>
                                {LANGUAGES.map(l => (
                                    <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
                                ))}
                            </select>
                        </div>
                    )}
                    
                    {mediaType === 'tv' && (
                        <>
                            <div style={{ display: 'flex', gap: 16, marginBottom: 14 }}>
                                <div style={{ flex: 1 }}>
                                    <div className="form-label" style={{ marginBottom: 6 }}>Season</div>
                                    <input className="form-input" type="number" placeholder="e.g. 15" value={season} onChange={e => setSeason(e.target.value)} required />
                                </div>
                                {!fullSeason && (
                                    <div style={{ flex: 1 }}>
                                        <div className="form-label" style={{ marginBottom: 6 }}>Episode</div>
                                        <input className="form-input" type="number" placeholder="e.g. 1" value={episode} onChange={e => setEpisode(e.target.value)} required={!fullSeason} />
                                    </div>
                                )}
                            </div>
                            <div style={{ marginBottom: 14 }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--text-primary)' }}>
                                    <input type="checkbox" checked={fullSeason} onChange={e => setFullSeason(e.target.checked)} />
                                    Download Full Season (All Episodes)
                                </label>
                            </div>
                        </>
                    )}

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
