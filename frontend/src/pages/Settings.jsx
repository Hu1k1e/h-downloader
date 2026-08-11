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

    const [sonarrStatus, setSonarrStatus] = useState(null)
    const [sonarrTesting, setSonarrTesting] = useState(false)
    const [sonarrMsg, setSonarrMsg] = useState('')

    const [radarrTesting, setRadarrTesting] = useState(false)
    const [tmdbTesting, setTmdbTesting] = useState(false)
    const [radarrMsg, setRadarrMsg] = useState('')
    const [copied, setCopied] = useState(false)
    
    const [importing, setImporting] = useState(false)
    const [importMsg, setImportMsg] = useState('')

    const [triggeringDiscovery, setTriggeringDiscovery] = useState(false)
    const [discoveryMsg, setDiscoveryMsg] = useState('')

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
                sonarr_url: data.sonarr_url,
                sonarr_api_key: '',
                sonarr_root_folder: data.sonarr_root_folder,
                radarr_api_key: '', // Empty means don't update
                jellyseerr_url: data.jellyseerr_url,
                jellyseerr_api_key: '',
                tmdb_api_key: '',
                einthusan_languages: data.einthusan_languages || [],
                digital_release_fallback_days: data.digital_release_fallback_days,
                sync_interval_seconds: data.sync_interval_seconds ?? 900,
                missing_search_interval_hours: data.missing_search_interval_hours ?? 24,
                missing_search_batch_size: data.missing_search_batch_size ?? 10,
                search_delay_seconds: data.search_delay_seconds ?? 120,
                movie_download_sources_priority: data.movie_download_sources_priority || ['einthusan', '1tamilmv'],
                tv_download_sources_priority: data.tv_download_sources_priority || ['1tamilmv', 'bollyzone'],
                qbittorrent_url: data.qbittorrent_url || '',
                qbittorrent_username: data.qbittorrent_username || '',
                qbittorrent_password: '',
                qbittorrent_category_movies: data.qbittorrent_category_movies || '',
                qbittorrent_category_series: data.qbittorrent_category_series || '',
                auto_delete_failed_torrents_hours: data.auto_delete_failed_torrents_hours ?? 24,
                min_file_size_mb: data.min_file_size_mb ?? 800,
                max_file_size_mb: data.max_file_size_mb ?? 15000,
                enable_jellyseerr_auto_request: data.enable_jellyseerr_auto_request ?? true,
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

    
    const moveSource = (index, direction, type) => {
        setFormData(prev => {
            const key = type === 'movie' ? 'movie_download_sources_priority' : 'tv_download_sources_priority'
            const newSources = [...(prev[key] || [])];
            if (direction === 'up' && index > 0) {
                [newSources[index - 1], newSources[index]] = [newSources[index], newSources[index - 1]];
            } else if (direction === 'down' && index < newSources.length - 1) {
                [newSources[index + 1], newSources[index]] = [newSources[index], newSources[index + 1]];
            }
            return { ...prev, [key]: newSources };
        });
    }

    const toggleSource = (source, type) => {
        setFormData(prev => {
            const key = type === 'movie' ? 'movie_download_sources_priority' : 'tv_download_sources_priority'
            const current = prev[key] || [];
            if (current.includes(source)) {
                return { ...prev, [key]: current.filter(s => s !== source) };
            } else {
                return { ...prev, [key]: [...current, source] };
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

    async function triggerDiscoveryBatch() {
        setTriggeringDiscovery(true)
        setDiscoveryMsg('')
        try {
            const res = await api.triggerDiscovery()
            setDiscoveryMsg(`Successfully triggered discovery for ${res.triggered} movies!`)
            setTimeout(() => setDiscoveryMsg(''), 5000)
        } catch (e) {
            setDiscoveryMsg(`Failed to trigger: ${e.message}`)
        } finally {
            setTriggeringDiscovery(false)
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


    
    async function testSonarr() {
        setSonarrTesting(true)
        setSonarrStatus(null)
        try {
            const r = await api.testSonarr()
            setSonarrStatus('ok')
            setSonarrMsg(r.version ? `v${r.version}` : '')
        } catch (e) {
            setSonarrStatus('err')
            setSonarrMsg(e.message)
        } finally {
            setSonarrTesting(false)
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

            
            {/* Sonarr */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Sonarr Connection</div>
                <div className="form-row">
                    <span className="form-label">URL</span>
                    <input className="form-input" name="sonarr_url" value={formData.sonarr_url} onChange={handleChange} placeholder="http://localhost:8989" />
                </div>
                <div className="form-row">
                    <span className="form-label">API Key</span>
                    <input className="form-input" name="sonarr_api_key" value={formData.sonarr_api_key} onChange={handleChange} placeholder={settings.sonarr_api_key_set ? '●●●●●●●●● (Set - Type to change)' : 'Not set'} />
                </div>
                <div className="form-row">
                    <span className="form-label">Root Folder</span>
                    <input className="form-input" name="sonarr_root_folder" value={formData.sonarr_root_folder} onChange={handleChange} placeholder="/series" />
                </div>
                <div className="form-row">
                    <span className="form-label">Connection</span>
                    <div className="connection-test-row">
                        <button className="btn btn-secondary btn-sm" onClick={testSonarr} disabled={sonarrTesting}>
                            {sonarrTesting ? <><span className="spinner" /> Testing…</> : 'Test Connection'}
                        </button>
                        {sonarrStatus === 'ok' && <span className="test-result ok">✓ Connected {sonarrMsg}</span>}
                        {sonarrStatus === 'err' && <span className="test-result err">✗ {sonarrMsg}</span>}
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
                <div className="settings-section-title">Movie Download Sources</div>
                <div className="form-row">
                    <span className="form-label">Active Sources</span>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 8 }}>
                            Check to enable. Drag arrows to set search priority.
                        </div>
                        {['1tamilmv', 'einthusan']
                            .sort((a, b) => {
                                const aIdx = (formData.movie_download_sources_priority || []).indexOf(a);
                                const bIdx = (formData.movie_download_sources_priority || []).indexOf(b);
                                if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
                                if (aIdx !== -1) return -1;
                                if (bIdx !== -1) return 1;
                                return a.localeCompare(b);
                            })
                            .map((source) => {
                                const isEnabled = (formData.movie_download_sources_priority || []).includes(source);
                                const idx = (formData.movie_download_sources_priority || []).indexOf(source);
                                return (
                                    <div key={source} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'var(--bg-tertiary)', marginBottom: 4, borderRadius: 6, opacity: isEnabled ? 1 : 0.6 }}>
                                        <input 
                                            type="checkbox" 
                                            checked={isEnabled} 
                                            onChange={() => toggleSource(source, 'movie')} 
                                            style={{ cursor: 'pointer' }}
                                        />
                                        <span style={{ fontWeight: 'bold', minWidth: 20 }}>{isEnabled ? `${idx + 1}.` : '-'}</span>
                                        <span style={{ flex: 1 }}>{source === '1tamilmv' ? '1TamilMV' : source === 'einthusan' ? 'Einthusan' : source}</span>
                                        {isEnabled && (
                                            <>
                                                <button className="btn btn-secondary btn-sm" onClick={() => moveSource(idx, 'up', 'movie')} disabled={idx === 0}>↑</button>
                                                <button className="btn btn-secondary btn-sm" onClick={() => moveSource(idx, 'down', 'movie')} disabled={idx === (formData.movie_download_sources_priority || []).length - 1}>↓</button>
                                            </>
                                        )}
                                    </div>
                                )
                            })}
                    </div>
                </div>

                <div className="settings-section-title" style={{ marginTop: 24 }}>TV Download Sources</div>
                <div className="form-row">
                    <span className="form-label">Active Sources</span>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 8 }}>
                            Check to enable. Drag arrows to set search priority.
                        </div>
                        {['1tamilmv', 'bollyzone']
                            .sort((a, b) => {
                                const aIdx = (formData.tv_download_sources_priority || []).indexOf(a);
                                const bIdx = (formData.tv_download_sources_priority || []).indexOf(b);
                                if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
                                if (aIdx !== -1) return -1;
                                if (bIdx !== -1) return 1;
                                return a.localeCompare(b);
                            })
                            .map((source) => {
                                const isEnabled = (formData.tv_download_sources_priority || []).includes(source);
                                const idx = (formData.tv_download_sources_priority || []).indexOf(source);
                                return (
                                    <div key={source} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'var(--bg-tertiary)', marginBottom: 4, borderRadius: 6, opacity: isEnabled ? 1 : 0.6 }}>
                                        <input 
                                            type="checkbox" 
                                            checked={isEnabled} 
                                            onChange={() => toggleSource(source, 'tv')} 
                                            style={{ cursor: 'pointer' }}
                                        />
                                        <span style={{ fontWeight: 'bold', minWidth: 20 }}>{isEnabled ? `${idx + 1}.` : '-'}</span>
                                        <span style={{ flex: 1 }}>{source === '1tamilmv' ? '1TamilMV' : source === 'bollyzone' ? 'Bollyzone' : source}</span>
                                        {isEnabled && (
                                            <>
                                                <button className="btn btn-secondary btn-sm" onClick={() => moveSource(idx, 'up', 'tv')} disabled={idx === 0}>↑</button>
                                                <button className="btn btn-secondary btn-sm" onClick={() => moveSource(idx, 'down', 'tv')} disabled={idx === (formData.tv_download_sources_priority || []).length - 1}>↓</button>
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
                    <span className="form-label">Discovery Interval</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                            className="form-input"
                            type="number"
                            name="missing_search_interval_hours"
                            value={formData.missing_search_interval_hours}
                            onChange={handleChange}
                            min={1}
                            style={{ maxWidth: 80 }}
                        />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>hours</span>
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Discovery Batch Size</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                            className="form-input"
                            type="number"
                            name="missing_search_batch_size"
                            value={formData.missing_search_batch_size}
                            onChange={handleChange}
                            min={1}
                            style={{ maxWidth: 80 }}
                        />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>movies to check per interval</span>
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">New Release Grace</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                            className="form-input"
                            type="number"
                            name="new_release_grace_hours"
                            value={formData.new_release_grace_hours}
                            onChange={handleChange}
                            min={0}
                            style={{ maxWidth: 80 }}
                        />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>hours — defer new releases to let Radarr/Sonarr grab quality first (0 = disabled)</span>
                    </div>
                </div>
                <div className="form-row">
                    <span className="form-label">Manual Trigger</span>
                    <div className="connection-test-row">
                        <button className="btn btn-secondary btn-sm" onClick={triggerDiscoveryBatch} disabled={triggeringDiscovery}>
                            {triggeringDiscovery ? <><span className="spinner" /> Triggering…</> : 'Run Discovery Now'}
                        </button>
                        {discoveryMsg && <span className={discoveryMsg.includes('Failed') ? 'test-result err' : 'test-result ok'}>{discoveryMsg}</span>}
                    </div>
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
