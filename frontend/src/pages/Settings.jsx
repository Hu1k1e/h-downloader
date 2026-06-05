import { useEffect, useState } from 'react'
import { api } from '../api'

const ALL_LANGS = ['malayalam', 'tamil', 'telugu', 'hindi', 'kannada', 'bengali', 'marathi', 'punjabi']

export default function Settings() {
    const [settings, setSettings] = useState(null)
    const [formData, setFormData] = useState({})
    const [saving, setSaving] = useState(false)
    const [saveMsg, setSaveMsg] = useState('')

    const [radarrStatus, setRadarrStatus] = useState(null)  // null | 'ok' | 'err'
    const [tmdbStatus, setTmdbStatus] = useState(null)
    const [radarrTesting, setRadarrTesting] = useState(false)
    const [tmdbTesting, setTmdbTesting] = useState(false)
    const [radarrMsg, setRadarrMsg] = useState('')
    const [copied, setCopied] = useState(false)
    
    const [importing, setImporting] = useState(false)
    const [importMsg, setImportMsg] = useState('')

    const [qbtTesting, setQbtTesting] = useState(false)
    const [qbtStatus, setQbtStatus] = useState(null)
    const [qbtMsg, setQbtMsg] = useState('')
    const [qbtCategories, setQbtCategories] = useState([])

    const loadSettings = () => {
        api.getSettings().then(data => {
            setSettings(data)
            setFormData({
                radarr_url: data.radarr_url,
                radarr_root_folder: data.radarr_root_folder,
                radarr_api_key: '', // Empty means don't update
                jellyseerr_url: data.jellyseerr_url,
                jellyseerr_api_key: '',
                tmdb_api_key: '',
                einthusan_languages: data.einthusan_languages || [],
                digital_release_fallback_days: data.digital_release_fallback_days,
                sync_interval_seconds: data.sync_interval_seconds ?? 900,
                missing_search_interval_hours: data.missing_search_interval_hours ?? 24,
                missing_search_batch_size: data.missing_search_batch_size ?? 10,
                download_sources_priority: data.download_sources_priority || ['einthusan', '1tamilmv'],
                qbittorrent_url: data.qbittorrent_url || '',
                qbittorrent_username: data.qbittorrent_username || '',
                qbittorrent_password: '',
                qbittorrent_category_movies: data.qbittorrent_category_movies || '',
                qbittorrent_category_series: data.qbittorrent_category_series || '',
                auto_delete_failed_torrents_hours: data.auto_delete_failed_torrents_hours ?? 24,
                min_file_size_mb: data.min_file_size_mb ?? 800,
                max_file_size_mb: data.max_file_size_mb ?? 15000,
                enable_jellyseerr_auto_request: data.enable_jellyseerr_auto_request ?? true,
                enable_radarr_auto_search: data.enable_radarr_auto_search ?? true,
            })

        }).catch(() => { })
    }


    useEffect(() => {
        loadSettings()
    }, [])

    const handleChange = (e) => {
        const { name, value } = e.target
        setFormData(prev => ({ ...prev, [name]: value }))
    }

    const toggleLanguage = (lang) => {
        setFormData(prev => {
            const current = prev.einthusan_languages || []
            if (current.includes(lang)) {
                return { ...prev, einthusan_languages: current.filter(l => l !== lang) }
            } else {
                return { ...prev, einthusan_languages: [...current, lang] }
            }
        })
    }

    const moveSource = (index, direction) => {
        setFormData(prev => {
            const newSources = [...(prev.download_sources_priority || [])];
            if (direction === 'up' && index > 0) {
                [newSources[index - 1], newSources[index]] = [newSources[index], newSources[index - 1]];
            } else if (direction === 'down' && index < newSources.length - 1) {
                [newSources[index + 1], newSources[index]] = [newSources[index], newSources[index + 1]];
            }
            return { ...prev, download_sources_priority: newSources };
        });
    }

    const toggleSource = (source) => {
        setFormData(prev => {
            const current = prev.download_sources_priority || [];
            if (current.includes(source)) {
                return { ...prev, download_sources_priority: current.filter(s => s !== source) };
            } else {
                return { ...prev, download_sources_priority: [...current, source] };
            }
        });
    }



    const handleSave = async () => {
        setSaving(true)
        setSaveMsg('')
        try {
            await api.updateSettings(formData)
            setSaveMsg('Settings saved successfully!')
            loadSettings() // refresh _set flags and version
            setTimeout(() => setSaveMsg(''), 3000)
        } catch (e) {
            setSaveMsg(`Error saving: ${e.message}`)
        } finally {
            setSaving(false)
        }
    }

    async function testRadarr() {
        setRadarrTesting(true)
        setRadarrStatus(null)
        try {
            const r = await api.testRadarr()
            setRadarrStatus('ok')
            setRadarrMsg(r.version ? `v${r.version}` : '')
        } catch (e) {
            setRadarrStatus('err')
            setRadarrMsg(e.message)
        } finally {
            setRadarrTesting(false)
        }
    }

    async function importRadarrMovies() {
        if (!window.confirm("This will fetch all movies from Radarr and import any that match your configured regional languages. Continue?")) return;
        setImporting(true)
        setImportMsg('')
        try {
            const res = await api.importRadarr()
            setImportMsg(`Successfully imported ${res.imported} movies!`)
        } catch (e) {
            setImportMsg(`Import failed: ${e.message}`)
        } finally {
            setImporting(false)
        }
    }

    async function testQbittorrent() {
        setQbtTesting(true)
        setQbtStatus(null)
        try {
            const res = await api.testQbittorrent({
                url: formData.qbittorrent_url,
                username: formData.qbittorrent_username,
                password: formData.qbittorrent_password || ''
            })
            setQbtStatus('ok')
            setQbtCategories(res.categories || [])
            setQbtMsg('Connected')
        } catch (e) {
            setQbtStatus('err')
            setQbtMsg(e.message)
            setQbtCategories([])
        } finally {
            setQbtTesting(false)
        }
    }


    async function testTmdb() {
        setTmdbTesting(true)
        setTmdbStatus(null)
        try {
            await api.testTmdb()
            setTmdbStatus('ok')
        } catch (e) {
            setTmdbStatus('err')
        } finally {
            setTmdbTesting(false)
        }
    }

    function copyWebhook() {
        const url = `${window.location.origin}/webhook/jellyseerr`
        navigator.clipboard.writeText(url)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    if (!settings) {
        return (
            <div className="main-content">
                <div style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="spinner" /> Loading settings…
                </div>
            </div>
        )
    }

    const webhookUrl = `${window.location.origin}/webhook/jellyseerr`

    return (
        <div className="main-content">
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">Settings</h1>
                    <p className="page-subtitle">Configure application settings and integrations</p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    {saveMsg && (
                        <span style={{ fontSize: '0.875rem', color: saveMsg.includes('Error') ? 'var(--danger)' : 'var(--success)' }}>
                            {saveMsg}
                        </span>
                    )}
                    <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                        {saving ? <><span className="spinner" style={{ marginRight: 8 }} />Saving...</> : 'Save Settings'}
                    </button>
                </div>
            </div>

            {/* Radarr */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Radarr Connection</div>
                <div className="form-row">
                    <span className="form-label">URL</span>
                    <input className="form-input" name="radarr_url" value={formData.radarr_url} onChange={handleChange} placeholder="http://localhost:7878" />
                </div>
                <div className="form-row">
                    <span className="form-label">API Key</span>
                    <input className="form-input" name="radarr_api_key" value={formData.radarr_api_key} onChange={handleChange} placeholder={settings.radarr_api_key_set ? '●●●●●●●●● (Set - Type to change)' : 'Not set'} />
                </div>
                <div className="form-row">
                    <span className="form-label">Root Folder</span>
                    <input className="form-input" name="radarr_root_folder" value={formData.radarr_root_folder} onChange={handleChange} placeholder="/movies" />
                </div>
                <div className="form-row">
                    <span className="form-label">Connection</span>
                    <div className="connection-test-row">
                        <button className="btn btn-secondary btn-sm" onClick={testRadarr} disabled={radarrTesting}>
                            {radarrTesting ? <><span className="spinner" /> Testing…</> : 'Test Connection'}
                        </button>
                        {radarrStatus === 'ok' && <span className="test-result ok">✓ Connected {radarrMsg}</span>}
                        {radarrStatus === 'err' && <span className="test-result err">✗ {radarrMsg}</span>}
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Import</span>
                    <div className="connection-test-row">
                        <button className="btn btn-secondary btn-sm" onClick={importRadarrMovies} disabled={importing || (!settings.radarr_api_key_set && !formData.radarr_api_key)}>
                            {importing ? <><span className="spinner" /> Importing…</> : 'Import Regional Movies'}
                        </button>
                        {importMsg && <span className="test-result" style={{color: importMsg.includes('failed') ? 'var(--danger)' : 'var(--success)'}}>{importMsg}</span>}
                    </div>
                </div>
            </div>

            {/* Jellyseerr */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Jellyseerr Connection</div>
                <div className="form-row">
                    <span className="form-label">URL</span>
                    <input className="form-input" name="jellyseerr_url" value={formData.jellyseerr_url} onChange={handleChange} placeholder="http://localhost:5055" />
                </div>
                <div className="form-row">
                    <span className="form-label">API Key</span>
                    <input className="form-input" name="jellyseerr_api_key" value={formData.jellyseerr_api_key} onChange={handleChange} placeholder={settings.jellyseerr_api_key_set ? '●●●●●●●●● (Set - Type to change)' : 'Not set'} />
                </div>
                <div className="form-row">
                    <span className="form-label">Webhook URL</span>
                    <div className="copy-input-wrap">
                        <input className="form-input" readOnly value={webhookUrl} />
                        <button className="btn btn-secondary btn-sm" onClick={copyWebhook}>
                            {copied ? '✓ Copied!' : '📋 Copy'}
                        </button>
                    </div>
                </div>
                <div style={{ marginTop: 12, padding: '10px 14px', background: 'var(--bg-tertiary)', borderRadius: 6, fontSize: 12, color: 'var(--text-secondary)', fontFamily: 'monospace', lineHeight: 1.8 }}>
                    <strong style={{ color: 'var(--text-primary)' }}>Jellyseerr Webhook JSON Payload:</strong><br />
                    {'{'}<br />
                    &nbsp;&nbsp;"notification_type": "{'{{notification_type}}'}",<br />
                    &nbsp;&nbsp;"media_type": "{'{{media_type}}'}",<br />
                    &nbsp;&nbsp;"tmdbId": "{'{{media_tmdbid}}'}",<br />
                    &nbsp;&nbsp;"title": "{'{{subject}}'}",<br />
                    {'}'}
                </div>
            </div>

            {/* TMDB */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">TMDB Settings</div>
                <div className="form-row">
                    <span className="form-label">API Key</span>
                    <input className="form-input" name="tmdb_api_key" value={formData.tmdb_api_key} onChange={handleChange} placeholder={settings.tmdb_api_key_set ? '●●●●●●●●● (Set - Type to change)' : 'Not set'} />
                </div>
                <div className="form-row">
                    <span className="form-label">Release Fallback</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input className="form-input" type="number" name="digital_release_fallback_days" value={formData.digital_release_fallback_days} onChange={handleChange} style={{ maxWidth: 80 }} />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>days after theatrical release</span>
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Connection</span>
                    <div className="connection-test-row">
                        <button className="btn btn-secondary btn-sm" onClick={testTmdb} disabled={tmdbTesting}>
                            {tmdbTesting ? <><span className="spinner" /> Testing…</> : 'Test Connection'}
                        </button>
                        {tmdbStatus === 'ok' && <span className="test-result ok">✓ Connected</span>}
                        {tmdbStatus === 'err' && <span className="test-result err">✗ Failed</span>}
                    </div>
                </div>
            </div>

            {/* Download Sources */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Download Sources</div>
                <div className="form-row">
                    <span className="form-label">Active Sources</span>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 8 }}>
                            Check to enable. Drag arrows to set search priority.
                        </div>
                        {['1tamilmv', 'einthusan']
                            .sort((a, b) => {
                                const aIdx = (formData.download_sources_priority || []).indexOf(a);
                                const bIdx = (formData.download_sources_priority || []).indexOf(b);
                                if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
                                if (aIdx !== -1) return -1;
                                if (bIdx !== -1) return 1;
                                return a.localeCompare(b);
                            })
                            .map((source) => {
                                const isEnabled = (formData.download_sources_priority || []).includes(source);
                                const idx = (formData.download_sources_priority || []).indexOf(source);
                                return (
                                    <div key={source} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'var(--bg-tertiary)', marginBottom: 4, borderRadius: 6, opacity: isEnabled ? 1 : 0.6 }}>
                                        <input 
                                            type="checkbox" 
                                            checked={isEnabled} 
                                            onChange={() => toggleSource(source)} 
                                            style={{ cursor: 'pointer' }}
                                        />
                                        <span style={{ fontWeight: 'bold', minWidth: 20 }}>{isEnabled ? `${idx + 1}.` : '-'}</span>
                                        <span style={{ flex: 1 }}>{source === '1tamilmv' ? '1TamilMV' : source === 'einthusan' ? 'Einthusan' : source}</span>
                                        {isEnabled && (
                                            <>
                                                <button className="btn btn-secondary btn-sm" onClick={() => moveSource(idx, 'up')} disabled={idx === 0}>↑</button>
                                                <button className="btn btn-secondary btn-sm" onClick={() => moveSource(idx, 'down')} disabled={idx === (formData.download_sources_priority || []).length - 1}>↓</button>
                                            </>
                                        )}
                                    </div>
                                )
                            })}
                    </div>
                </div>
            </div>

            {/* qBittorrent */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">qBittorrent Settings</div>
                <div className="form-row">
                    <span className="form-label">URL</span>
                    <input className="form-input" name="qbittorrent_url" value={formData.qbittorrent_url || ''} onChange={handleChange} placeholder="http://localhost:8080" />
                </div>
                <div className="form-row">
                    <span className="form-label">Username</span>
                    <input className="form-input" name="qbittorrent_username" value={formData.qbittorrent_username || ''} onChange={handleChange} placeholder="admin" />
                </div>
                <div className="form-row">
                    <span className="form-label">Password</span>
                    <input className="form-input" type="password" name="qbittorrent_password" value={formData.qbittorrent_password || ''} onChange={handleChange} placeholder={settings.qbittorrent_password_set ? '●●●●●●●●● (Set - Type to change)' : 'Not set'} />
                </div>
                <div className="form-row">
                    <span className="form-label">Connection</span>
                    <div className="connection-test-row">
                        <button className="btn btn-secondary btn-sm" onClick={testQbittorrent} disabled={qbtTesting}>
                            {qbtTesting ? <><span className="spinner" /> Testing…</> : 'Test Connection'}
                        </button>
                        {qbtStatus === 'ok' && <span className="test-result ok">✓ {qbtMsg}</span>}
                        {qbtStatus === 'err' && <span className="test-result err">✗ {qbtMsg}</span>}
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Movies Category</span>
                    {qbtCategories.length > 0 ? (
                        <select className="form-input" name="qbittorrent_category_movies" value={formData.qbittorrent_category_movies || ''} onChange={handleChange}>
                            <option value="">(None)</option>
                            {qbtCategories.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                        </select>
                    ) : (
                        <input className="form-input" name="qbittorrent_category_movies" value={formData.qbittorrent_category_movies || ''} onChange={handleChange} placeholder="radarr" />
                    )}
                </div>
                <div className="form-row">
                    <span className="form-label">Series Category</span>
                    {qbtCategories.length > 0 ? (
                        <select className="form-input" name="qbittorrent_category_series" value={formData.qbittorrent_category_series || ''} onChange={handleChange}>
                            <option value="">(None)</option>
                            {qbtCategories.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                        </select>
                    ) : (
                        <input className="form-input" name="qbittorrent_category_series" value={formData.qbittorrent_category_series || ''} onChange={handleChange} placeholder="sonarr" />
                    )}
                </div>
                <div className="form-row">
                    <span className="form-label">Auto Delete Failed</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input className="form-input" type="number" name="auto_delete_failed_torrents_hours" value={formData.auto_delete_failed_torrents_hours} onChange={handleChange} style={{ maxWidth: 80 }} />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>hours</span>
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Min File Size</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input className="form-input" type="number" name="min_file_size_mb" value={formData.min_file_size_mb} onChange={handleChange} style={{ maxWidth: 100 }} />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>MB</span>
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Max File Size</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input className="form-input" type="number" name="max_file_size_mb" value={formData.max_file_size_mb} onChange={handleChange} style={{ maxWidth: 100 }} />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>MB</span>
                    </div>
                </div>
            </div>

            {/* Scheduler */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Automations</div>
                <div className="form-row">
                    <span className="form-label">Search Delay</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                            className="form-input"
                            type="number"
                            name="search_delay_seconds"
                            value={formData.search_delay_seconds}
                            onChange={handleChange}
                            min={0}
                            style={{ maxWidth: 100 }}
                        />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>seconds — how long to wait after a movie is added to Radarr before triggering fallback search</span>
                    </div>
                </div>
            </div>

            {/* Automation */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Automation</div>
                <div className="form-row">
                    <span className="form-label">Jellyseerr</span>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--text-primary)' }}>
                        <input type="checkbox" name="enable_jellyseerr_auto_request" checked={formData.enable_jellyseerr_auto_request} onChange={e => setFormData(p => ({...p, enable_jellyseerr_auto_request: e.target.checked}))} />
                        Automatically import approved movies from Jellyseerr
                    </label>
                </div>
                <div className="form-row">
                    <span className="form-label">Radarr</span>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--text-primary)' }}>
                        <input type="checkbox" name="enable_radarr_auto_search" checked={formData.enable_radarr_auto_search} onChange={e => setFormData(p => ({...p, enable_radarr_auto_search: e.target.checked}))} />
                        Automatically search Radarr missing movies
                    </label>
                </div>
            </div>

            {/* Einthusan Languages */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Einthusan Languages</div>
                <div className="form-row">
                    <span className="form-label">Monitored Languages</span>
                    <div className="lang-grid">
                        {ALL_LANGS.map(l => {
                            const selected = formData.einthusan_languages.includes(l)
                            return (
                                <span
                                    key={l}
                                    onClick={() => toggleLanguage(l)}
                                    className={`lang-chip${selected ? ' active' : ''}`}
                                    style={{ cursor: 'pointer' }}
                                >
                                    {selected ? '✓' : '○'}
                                    {' '}{l.charAt(0).toUpperCase() + l.slice(1)}
                                </span>
                            )
                        })}
                    </div>
                </div>
            </div>

            {/* Version */}
            <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', marginTop: 24 }}>
                H-Downloader {settings.app_version}
            </div>
        </div>
    )
}
