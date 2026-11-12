/**
 * Node ESM loader hooks for running the Vite/React app under plain Node.
 *
 * - `tsconfig-alias.mjs` maps the `@/` import alias to `src/`.
 * - `css-stub.mjs` turns `.css` imports into empty modules.
 *
 * Register with:
 *   npx tsx --import ./scripts/tsx-hooks-register.mjs scripts/smoke.tsx
 *
 * The `@/` alias must resolve through tsconfig.app.json, so we point tsx at it
 * here rather than relying on a POSIX-only `TSX_TSCONFIG_PATH=...` prefix in
 * package.json (which fails under cmd.exe on Windows).
 */
import { register } from 'node:module'
import { pathToFileURL } from 'node:url'
import path from 'node:path'

process.env.TSX_TSCONFIG_PATH = path.resolve(process.cwd(), 'tsconfig.app.json')

register('./tsconfig-alias.mjs', import.meta.url)
register('./css-stub.mjs', import.meta.url)

export const tsconfigUrl = pathToFileURL(process.env.TSX_TSCONFIG_PATH).href
