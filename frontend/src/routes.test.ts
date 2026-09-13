import { legacyRouteTarget } from './routes'

if (legacyRouteTarget('/groups') !== '/themes') throw new Error('groups should redirect to themes')
if (legacyRouteTarget('/signals') !== '/actions') throw new Error('signals should redirect to actions')
if (legacyRouteTarget('/data-quality') !== '/system/data-quality') throw new Error('data quality route should remain system-only')
if (legacyRouteTarget('/instruments/AAA', '?exchange=TWSE') !== '/stocks/TWSE/AAA') throw new Error('instrument detail should preserve exchange identity')
