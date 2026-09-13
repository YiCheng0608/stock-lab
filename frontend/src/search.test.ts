import { commitSearchOnEnter } from './search'

const submitted = commitSearchOnEnter('  2330  ', 'Enter')
if (submitted !== '2330') throw new Error('Enter should commit a trimmed search value')
if (commitSearchOnEnter('2330', 'a') !== null) throw new Error('typing must not commit a search value')
if (commitSearchOnEnter('', 'Enter') !== '') throw new Error('Enter should allow clearing to an empty query')
