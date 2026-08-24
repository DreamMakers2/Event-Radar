import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'

const assetsDir = path.resolve(process.cwd(), '../event_radar/static/app/assets')
const limits = {
  jsGzip: 120 * 1024,
  cssGzip: 25 * 1024,
}

let totalJs = 0
let totalCss = 0
let totalJsGzip = 0
let totalCssGzip = 0

for (const entry of fs.readdirSync(assetsDir)) {
  const fullPath = path.join(assetsDir, entry)
  const stats = fs.statSync(fullPath)
  if (!stats.isFile()) continue
  const gzipSize = zlib.gzipSync(fs.readFileSync(fullPath)).byteLength
  if (entry.endsWith('.js')) {
    totalJs += stats.size
    totalJsGzip += gzipSize
  }
  if (entry.endsWith('.css')) {
    totalCss += stats.size
    totalCssGzip += gzipSize
  }
}

if (totalJsGzip > limits.jsGzip) {
  throw new Error(`JavaScript gzip bundle too large: ${totalJsGzip} bytes > ${limits.jsGzip} bytes`)
}

if (totalCssGzip > limits.cssGzip) {
  throw new Error(`CSS gzip bundle too large: ${totalCssGzip} bytes > ${limits.cssGzip} bytes`)
}

console.log(
  `Bundle check passed: JS=${totalJs} bytes (${totalJsGzip} gzip) CSS=${totalCss} bytes (${totalCssGzip} gzip)`,
)
