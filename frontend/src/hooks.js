import { useEffect, useRef } from 'react'

/**
 * Call `fn` immediately and then every `ms` milliseconds, but only while the browser tab is
 * visible (a hidden tab no longer hammers the API every few seconds). Refreshes right away
 * when the tab becomes visible again.
 */
export function usePolling(fn, ms, deps = []) {
    const saved = useRef(fn)
    saved.current = fn

    useEffect(() => {
        let timer = null
        const tick = () => saved.current()
        const start = () => {
            if (timer == null) timer = setInterval(tick, ms)
        }
        const stop = () => {
            if (timer != null) {
                clearInterval(timer)
                timer = null
            }
        }
        const onVisibility = () => {
            if (document.hidden) {
                stop()
            } else {
                tick()
                start()
            }
        }

        tick()
        if (!document.hidden) start()
        document.addEventListener('visibilitychange', onVisibility)
        return () => {
            stop()
            document.removeEventListener('visibilitychange', onVisibility)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ms, ...deps])
}
