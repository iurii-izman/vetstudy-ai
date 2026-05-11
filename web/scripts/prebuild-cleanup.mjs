import { rm, unlink } from 'node:fs/promises'

const DIST_DIR = new URL('../dist/', import.meta.url)
const ASSETS_DIR = new URL('./assets/', DIST_DIR)
const DIST_INDEX = new URL('./index.html', DIST_DIR)
const DIST_404 = new URL('./404.html', DIST_DIR)

const RETRIABLE_ERROR_CODES = new Set(['EBUSY', 'EPERM', 'ENOTEMPTY'])
const MAX_RETRIES = 8
const BASE_DELAY_MS = 150

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function withRetry(action, label) {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      await action()
      return true
    } catch (error) {
      if (error?.code === 'ENOENT') {
        return true
      }

      const canRetry = RETRIABLE_ERROR_CODES.has(error?.code) && attempt < MAX_RETRIES
      if (!canRetry) {
        console.warn(`[prebuild-cleanup] ${label} skipped: ${error?.code ?? 'UNKNOWN'} ${error?.message ?? ''}`)
        return false
      }

      const waitFor = BASE_DELAY_MS * attempt
      console.warn(`[prebuild-cleanup] ${label} busy (${error.code}), retry ${attempt}/${MAX_RETRIES} in ${waitFor}ms`)
      await sleep(waitFor)
    }
  }

  return false
}

async function safeRm(pathLike, label) {
  return withRetry(() => rm(pathLike, { recursive: true, force: true }), label)
}

async function safeUnlink(pathLike, label) {
  return withRetry(() => unlink(pathLike), label)
}

async function main() {
  await safeRm(ASSETS_DIR, 'dist/assets')
  await safeUnlink(DIST_INDEX, 'dist/index.html')
  await safeUnlink(DIST_404, 'dist/404.html')

  // Keep other dist files to avoid hard-failing when a watcher briefly locks the directory.
  console.log('[prebuild-cleanup] completed')
}

main().catch((error) => {
  console.warn(`[prebuild-cleanup] finished with warning: ${error?.message ?? error}`)
  process.exitCode = 0
})
