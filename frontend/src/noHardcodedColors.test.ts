// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
declare const __filename: string
type DirEntry = { name: string; isDirectory(): boolean }
const fs = require('node:fs') as { readdirSync(dir: string, options: { withFileTypes: true }): DirEntry[]; readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string; relative(from: string, to: string): string; basename(file: string): string; sep: string }

// Standalone regression module (no browser, no server). DESIGN_SYSTEM §2/§9: color literals live only in
// styles/tokens.css; every component, page and stylesheet in src goes through the CSS variables.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }

// scripts/ci-test.cjs compiles this file to CJS, so __dirname is src.
const srcRoot = __dirname
const TOKENS = 'styles/tokens.css'
const SCANNED = /\.(tsx?|css)$/
// Hex colors (#rgb, #rgba, #rrggbb, #rrggbbaa) not preceded by & (HTML entity) or a word character, and color functions.
const HEX = /(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z_-])/g
const FUNCTION = /\b(?:rgba?|hsla?)\(/g

// Comments are prose (e.g. "PR #155"), not styles: block comments and // line comments (not the // inside https://) are dropped.
export function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[\s;])\/\/.*$/gm, '$1')
}

export function colorLiterals(text: string): string[] {
  const code = stripComments(text)
  return [...code.matchAll(HEX), ...code.matchAll(FUNCTION)].map((match) => match[0])
}

function listFiles(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) listFiles(full, found)
    else if (SCANNED.test(entry.name)) found.push(path.relative(srcRoot, full).split(path.sep).join('/'))
  }
  return found
}

// The pattern itself: positives and the HTML-entity / id-selector negatives it must not flag.
check(colorLiterals("color: '#e899a0'").join() === '#e899a0', 'six-digit hex is flagged')
check(colorLiterals('border: 1px solid #fff;').join() === '#fff', 'three-digit hex is flagged')
check(colorLiterals('background: rgba(0, 0, 0, .5)').join() === 'rgba(', 'rgba() is flagged')
check(colorLiterals('fill: hsl(10 20% 30%)').join() === 'hsl(', 'hsl() is flagged')
check(colorLiterals("replace(/'/g, '&#39;')").length === 0, 'HTML entities are not colors')
check(colorLiterals('var(--color-up) #root-cause').length === 0, 'variables and non-color hashes are not flagged')
check(colorLiterals('// PR #155 shape\n/* #fff */ ok').length === 0, 'comments are not scanned')
check(colorLiterals("const url = 'https://x.test' // note #123\nconst c = '#abc'").join() === '#abc', 'code after a URL line is still scanned')

const files = listFiles(srcRoot)
check(files.includes(TOKENS), 'tokens.css exists')
check(files.includes('styles.css') && files.some((file) => file.startsWith('components/ui/')), 'scan reaches the page stylesheet and ui components')
check(colorLiterals(fs.readFileSync(path.join(srcRoot, TOKENS), 'utf8')).length > 0, 'tokens.css is where the color literals are')

const self = path.basename(__filename)
const offenders = files
  .filter((file) => file !== TOKENS && path.basename(file) !== self)
  .flatMap((file) => colorLiterals(fs.readFileSync(path.join(srcRoot, file), 'utf8')).map((literal) => `${file}: ${literal}`))
check(offenders.length === 0, `hard-coded colors outside ${TOKENS}:\n${offenders.join('\n')}`)
