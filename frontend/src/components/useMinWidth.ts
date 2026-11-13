import { useEffect, useState } from 'react'

// Whether the viewport is at least `width` px wide, following resizes. Read on the first render, so a narrow page never
// renders the wide layout first (#665: the today list's chart must not mount below 1280px). False without a window.
export function useMinWidth(width: number): boolean {
  const query = `(min-width: ${width}px)`
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = () => setMatches(media.matches)
    onChange()
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [query])
  return matches
}
