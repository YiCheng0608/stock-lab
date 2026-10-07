import { calendarJointFixture, jointFixtureGraphBytes } from './savedPriceChipsFocus.test'
import { validCalendarWindowIdentity, validCalendarWindowRead } from './institutionalWindows'

export let largestCalendarWindowFixtureGraphBytes = 0

export function runCalendarWindowTests(): number {
  let checks = 0
  const check = (value: unknown, message: string) => { checks++; if (!value) throw new Error(message) }
  const data = calendarJointFixture()
  const read = data.institutional[0]
  check(validCalendarWindowIdentity(read, 'TPEx', '3105', '2026-10-06'), 'new identity')
  check(validCalendarWindowRead(read, 'TPEx', '3105', '2026-10-06'), 'all25 original rows and24 adopted')
  check(!validCalendarWindowRead(read, 'TPEx', '6488', '2026-10-06'), 'symbol mismatch')
  check(!validCalendarWindowRead(read, 'TPEx', '3105', '2026-10-07'), 'cutoff mismatch')
  const reject = (mutate: (copy: typeof read) => void, name: string) => {
    const copy = structuredClone(read)
    mutate(copy)
    check(!validCalendarWindowRead(copy), name)
    largestCalendarWindowFixtureGraphBytes = Math.max(largestCalendarWindowFixtureGraphBytes, jointFixtureGraphBytes([data, copy]))
    check(largestCalendarWindowFixtureGraphBytes <= 524288, 'held original plus corruption branch graph cap')
  }
  reject((copy) => { copy.calendar!.original_rows!.pop() }, 'post-cutoff row is required')
  reject((copy) => { copy.calendar!.original_rows![24].source_values['開市'] = 'NaN' }, 'post-cutoff numeric invalid')
  reject((copy) => { copy.calendar!.original_rows![24].source_values['最高價'] = '8' }, 'post-cutoff OHLC invalid')
  reject((copy) => { copy.calendar!.original_rows![24].date = '2026-10-08' }, 'future observed date')
  reject((copy) => { copy.calendar!.original_valid_dates!.push('2026-10-08') }, 'future extra date')
  reject((copy) => { copy.calendar!.evidence![1].candidate_count = 4 }, 'original count differs from adoption')
  reject((copy) => { copy.calendar!.rows = copy.calendar!.original_rows }, 'future row cannot enter adopted24')
  reject((copy) => { copy.provenance!.captured_versions.pop() }, 'all22 captures required')
  reject((copy) => { copy.windows!['20'].daily_evidence![19].row.investors.foreign.net = '1' }, 'full raw relation validation')
  reject((copy) => { copy.windows!['20'].daily_evidence![19].row.source_values!['外資及陸資買賣超股數'] = '1' }, 'exclude external dealer and preserve seven financial relations')
  return checks
}
