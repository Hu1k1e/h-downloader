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
