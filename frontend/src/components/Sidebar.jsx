import { NavLink } from 'react-router-dom'

const NAV = [
    { to: '/', label: 'Dashboard' },
    { to: '/movies', label: 'Movies' },
    { to: '/jobs', label: 'Jobs' },
    { to: '/settings', label: 'Settings' },
]

export default function Sidebar() {
    return (
        <aside className="sidebar">
            <div className="sidebar-logo">
                <img
                    src="/logo.png"
                    alt="H Downloader"
                    style={{ width: 40, height: 40, objectFit: 'contain' }}
                />
                <div>
                    <div className="sidebar-logo-text">H Downloader</div>
                    <div className="sidebar-logo-sub">Auto movie downloader</div>
                </div>
            </div>

            <nav className="sidebar-nav">
                {NAV.map(({ to, label }) => (
                    <NavLink
                        key={to}
                        to={to}
                        end={to === '/'}
                        className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
                    >
                        {label}
                    </NavLink>
                ))}
            </nav>

            <div className="sidebar-footer">H Downloader v1.0</div>
        </aside>
    )
}
