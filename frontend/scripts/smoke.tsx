/**
 * Runtime smoke test for the AgentGuard dashboard shell.
 *
 * Renders the real app (components + data layer + styles) into a DOM and
 * asserts that the shell, navigation, and overview content actually appear.
 *
 * Run with: npm run smoke
 */
import { JSDOM } from 'jsdom'

// Vite replaces `import.meta.env` at build time; shim it for Node/tsx.
;(globalThis as Record<string, unknown>).__AGENTGUARD_USE_MOCK__ = 'true'
;(globalThis as Record<string, unknown>).__AGENTGUARD_API_BASE__ = '/api/v1'

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
})

const g = globalThis as Record<string, unknown>
g.window = dom.window
g.document = dom.window.document
Object.defineProperty(globalThis, 'navigator', {
  value: dom.window.navigator,
  configurable: true,
  writable: true,
})
g.HTMLElement = dom.window.HTMLElement
g.Element = dom.window.Element
g.Node = dom.window.Node
g.Event = dom.window.Event
g.MouseEvent = dom.window.MouseEvent
g.getComputedStyle = dom.window.getComputedStyle.bind(dom.window)
g.requestAnimationFrame = (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 0)
g.cancelAnimationFrame = (id: number) => clearTimeout(id)
dom.window.matchMedia =
  dom.window.matchMedia ??
  ((query: string) => ({
    matches: false,
    media: query,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }))

async function main() {
  const React = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { BrowserRouter } = await import('react-router-dom')

  // Import after globals are installed so React DOM binds to our jsdom window.
  const { DataProvider } = await import('../src/api/DataContext')
  const { AppRoutes } = await import('../src/App')

  const root = createRoot(document.getElementById('root')!)
  root.render(
    React.createElement(
      BrowserRouter,
      null,
      React.createElement(DataProvider, null, React.createElement(AppRoutes)),
    ),
  )

  // Let effects run and the mock API resolve its simulated latency.
  await new Promise((r) => setTimeout(r, 800))

  const text = document.body.textContent ?? ''
  const nav = Array.from(document.querySelectorAll('a')).map((a) => a.textContent?.trim())

  const checks: Array<[string, boolean]> = [
    ['brand renders', text.includes('AgentGuard')],
    ['nav has Overview', nav.some((n) => n?.includes('Overview'))],
    ['nav has Agents', nav.some((n) => n?.includes('Agents'))],
    ['nav has Tools', nav.some((n) => n?.includes('Tools'))],
    ['nav has Policies', nav.some((n) => n?.includes('Policies'))],
    ['nav has Approvals', nav.some((n) => n?.includes('Approvals'))],
    ['nav has Activity', nav.some((n) => n?.includes('Activity'))],
    ['nav has Settings', nav.some((n) => n?.includes('Settings'))],
    ['overview stat rendered', text.includes('Active agents')],
    ['pending approvals section', text.includes('Needs attention')],
    ['recent decisions section', text.includes('Recent decisions')],
    ['seed agent appears', text.includes('support-agent')],
    ['seed tool appears', text.includes('search_knowledge_base')],
    ['decision badge appears', text.includes('Allowed')],
    ['blocked badge appears', text.includes('Blocked')],
    ['risk badge appears', text.includes('HIGH') || text.includes('CRITICAL')],
    ['mode pill shows demo data', text.includes('Demo data')],
    ['skip link present', !!document.querySelector('.skip-link')],
    ['no error banner', !text.includes('Cannot reach the AgentGuard API')],
  ]

  let failed = 0
  for (const [label, ok] of checks) {
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`)
    if (!ok) failed++
  }

  console.log('\n--- nav links ---')
  console.log(nav.filter(Boolean).join(' | '))
  console.log(`\nrendered ${text.length} chars of text`)
  console.log(`root has ${document.getElementById('root')?.childElementCount ?? 0} child element(s)`)

  if (failed > 0) {
    console.log(`\n${failed} check(s) FAILED`)
    process.exit(1)
  }
  console.log('\nAll checks passed.')
}

main().catch((err) => {
  console.error('Smoke test crashed:', err)
  process.exit(1)
})
