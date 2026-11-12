/**
 * Node ESM load hook that turns `.css` imports into empty modules.
 *
 * The smoke test asserts on rendered DOM content, not styles, so an empty
 * stylesheet is sufficient and keeps Node from choking on CSS syntax.
 */
export async function load(url, context, nextLoad) {
  if (url.endsWith('.css')) {
    return {
      format: 'module',
      shortCircuit: true,
      source: 'export default {}',
    }
  }
  return nextLoad(url, context)
}
