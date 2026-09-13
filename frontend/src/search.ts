/**
 * Convert a draft search value into a committed query only for Enter.
 * Keeping this pure makes the no-request-on-every-keystroke contract easy to
 * exercise independently of the page components.
 */
export function commitSearchOnEnter(draft: string, key: string): string | null {
  return key === 'Enter' ? draft.trim() : null
}
