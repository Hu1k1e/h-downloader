export function StatusBadge({ status }) {
    const labels = {
        downloading: '⬇ Downloading',
        done: '✓ Done',
        failed: '✗ Failed',
        searching: '🔍 Searching',
        not_found: '— Not Found',
        pending: '⏳ Pending',
        checking_radarr: '🔍 Checking',
        importing: '📥 Importing',
        skipped: '⏭ Skipped',
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
                style={{ width: `${Math.min(pct, 100)}%` }}
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
