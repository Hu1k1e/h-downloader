import { useEffect, useState } from 'react'

const toastListeners = new Set()

/** Show a transient message. type: 'info' | 'success' | 'error' */
export function toast(message, type = 'info', ms = 5000) {
    toastListeners.forEach(l => l({ id: Date.now() + Math.random(), message, type, ms: type === 'error' ? Math.max(ms, 8000) : ms }))
}

export function ToastHost() {
    const [items, setItems] = useState([])
    useEffect(() => {
        const listener = (t) => {
            setItems(prev => [...prev.slice(-3), t])
            setTimeout(() => setItems(prev => prev.filter(x => x.id !== t.id)), t.ms)
        }
        toastListeners.add(listener)
        return () => { toastListeners.delete(listener) }
    }, [])
    return (
        <div className="toast-host" role="status" aria-live="polite">
            {items.map(t => (
                <div key={t.id} className={`toast toast-${t.type}`} onClick={() => setItems(prev => prev.filter(x => x.id !== t.id))}>
                    {t.message}
                </div>
            ))}
        </div>
    )
}

export function StatusBadge({ status }) {
    const labels = {
        downloading: 'Downloading',
        done: 'Done',
        failed: 'Failed',
        searching: 'Searching',
        not_found: 'Not Found',
        pending: 'Pending',
        checking_radarr: 'Checking',
        importing: 'Importing',
        skipped: 'Skipped',
        movie_missing: 'File Missing',
        not_in_radarr: 'Not in Radarr/Sonarr',
        discovered: 'Discovered',
    }
    return (
        <span className={`badge badge-${status}`}>
            {labels[status] || status}
        </span>
    )
}

export function ProgressBar({ pct, style }) {
    return (
        <div className="progress-bar-wrap" style={style}>
            <div
                className="progress-bar-fill"
                style={{ width: `${Math.min(pct ?? 0, 100)}%` }}
            />
        </div>
    )
}

export function formatBytes(bytes) {
    if (!bytes) return '—'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export function timeAgo(dateStr) {
    if (!dateStr) return '—'
    const diff = Date.now() - new Date(dateStr + 'Z').getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h ago`
    return `${Math.floor(hours / 24)}d ago`
}

export function formatETA(seconds) {
    if (seconds == null || isNaN(seconds)) return null;
    if (seconds === 8640000) return '∞';
    
    if (seconds < 60) return `${Math.floor(seconds)}s left`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m left`;
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    if (hours < 24) return `${hours}h ${remMins}m left`;
    
    const days = Math.floor(hours / 24);
    const remHours = hours % 24;
    return `${days}d ${remHours}h left`;
}

export function formatAirDate(dateStr) {
    if (!dateStr) return null;
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return null;

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const checkDate = new Date(date);
    checkDate.setHours(0, 0, 0, 0);

    const diffTime = checkDate - today;
    const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === -1) return 'Yesterday';
    if (diffDays === 1) return 'Tomorrow';

    if (diffDays > 1 && diffDays < 7) {
        return checkDate.toLocaleDateString('en-US', { weekday: 'long' });
    }

    return checkDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
