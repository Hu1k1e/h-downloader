import { useEffect, useState } from 'react'
import { api } from '../api'

const ALL_LANGS = ['malayalam', 'tamil', 'telugu', 'hindi', 'kannada', 'bengali', 'marathi', 'punjabi', 'hollywood']

export default function Settings() {
    const [settings, setSettings] = useState(null)
    const [formData, setFormData] = useState({})
    const [saving, setSaving] = useState(false)
    const [saveMsg, setSaveMsg] = useState('')

    const [radarrStatus, setRadarrStatus] = useState(null)  // null | 'ok' | 'err'
    const [sonarrStatus, setSonarrStatus] = useState(null)
    const [tmdbStatus, setTmdbStatus] = useState(null)
    const [radarrTesting, setRadarrTesting] = useState(false)
    const [sonarrTesting, setSonarrTesting] = useState(false)
    const [tmdbTesting, setTmdbTesting] = useState(false)
    const [radarrMsg, setRadarrMsg] = useState('')
    const [sonarrMsg, setSonarrMsg] = useState('')
    const [copied, setCopied] = useState(false)
    
    const [importing, setImporting] = useState(false)
    const [importMsg, setImportMsg] = useState('')

    const loadSettings = () => {
        api.getSettings().then(data => {
            setSettings(data)
            setFormData({
                radarr_url: data.radarr_url,
                radarr_root_folder: data.radarr_root_folder,
                radarr_api_key: '', // Empty means don't update
                sonarr_url: data.sonarr_url,
                sonarr_root_folder: data.sonarr_root_folder,
                sonarr_api_key: '',
                jellyseerr_url: data.jellyseerr_url,
                jellyseerr_api_key: '',
                tmdb_api_key: '',
                einthusan_languages: data.einthusan_languages || [],
                digital_release_fallback_days: data.digital_release_fallback_days,
                sync_interval_seconds: data.sync_interval_seconds ?? 900,
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
                    <input className="form-input" name="sonarr_root_folder" value={formData.sonarr_root_folder} onChange={handleChange} placeholder="/tv" />
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

            {/* Scheduler */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">Scheduler</div>
                <div className="form-row">
                    <span className="form-label">Sync Interval</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                            className="form-input"
                            type="number"
                            name="sync_interval_seconds"
                            value={formData.sync_interval_seconds}
                            onChange={handleChange}
                            min={30}
                            style={{ maxWidth: 100 }}
                        />
                        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>seconds (min 30) — how often to poll Jellyseerr and sync with Radarr</span>
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
