// Every displayed date goes through here (UI_COPY_SPEC §1): YYYY/MM/DD, and 24-hour YYYY/MM/DD HH:mm in
// Asia/Taipei. Intl is used only in this file, so no page picks up the zh-TW locale's 上午／下午.

const TAIPEI_PARTS = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

/** The calendar day of an ISO date (or the date part of a timestamp), without shifting time zones. */
export function formatDay(value: string | null | undefined): string | null {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null
  return match ? `${match[1]}/${match[2]}/${match[3]}` : null
}

// Backend timestamps without an offset are UTC.
function parseInstant(value: string): Date | null {
  const parsed = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z')
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function taipeiParts(value: string | null | undefined): Record<string, string> | null {
  const parsed = value ? parseInstant(value) : null
  return parsed ? Object.fromEntries(TAIPEI_PARTS.formatToParts(parsed).map((part) => [part.type, part.value])) : null
}

/** An instant as Taipei YYYY/MM/DD HH:mm; null when it does not parse. */
export function formatTaipeiMinute(value: string | null | undefined): string | null {
  const parts = taipeiParts(value)
  return parts ? `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}` : null
}

/** The Taipei calendar day of an instant; null when it does not parse. */
export function formatTaipeiDay(value: string | null | undefined): string | null {
  const parts = taipeiParts(value)
  return parts ? `${parts.year}/${parts.month}/${parts.day}` : null
}
