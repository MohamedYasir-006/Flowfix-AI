/**
 * Node ESM resolve hook that maps the `@/` path alias to `src/`,
 * matching tsconfig.app.json and vite.config.ts.
 */
import { pathToFileURL } from 'node:url'
import path from 'node:path'

const SRC = pathToFileURL(path.resolve(process.cwd(), 'src') + path.sep).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('@/')) {
    return nextResolve(SRC + specifier.slice(2), context)
  }
  return nextResolve(specifier, context)
}
