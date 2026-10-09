// Run the existing standalone regression modules in memory, without a server.
const path = require('node:path')
const Module = require('node:module')
const root = path.resolve(__dirname, '..')
const viteRequire = Module.createRequire(require.resolve('vite/package.json'))
const esbuild = viteRequire('esbuild')
const tests = ['units', 'search', 'routes', 'presentation', 'stockChart']
for (const name of tests) {
  const filename = path.join(root, 'src', `${name}.test.ts`)
  const result = esbuild.buildSync({
    entryPoints: [filename], bundle: true, platform: 'node', format: 'cjs',
    write: false, logLevel: 'error',
  })
  const testModule = new Module(filename, module)
  testModule.filename = filename
  testModule.paths = Module._nodeModulePaths(path.dirname(filename))
  testModule._compile(result.outputFiles[0].text, filename)
  console.log(`PASS ${name}.test.ts`)
}
console.log(`Passed ${tests.length} standalone modules; this is not browser or full product QA.`)
