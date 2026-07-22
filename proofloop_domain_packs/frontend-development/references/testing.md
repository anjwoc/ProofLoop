# Frontend Testing Reference

Cross-framework guide for component and interaction testing.

## Choosing the right test layer

| What you want to verify | Layer | Tool |
|---|---|---|
| Logic in isolation | Unit | vitest / jest |
| Component renders/behavior | Component | @testing-library/* |
| Full user flow across pages | E2E | Playwright / Cypress |
| Visual regressions | Visual | Playwright screenshots |
| Accessibility | A11y | axe-core, Pa11y |

**Rule**: Use the narrowest layer that can observe the failure. An E2E test that could be a component test is 10x slower and 10x flakier.

## Query priority (all testing-library variants)

```
getByRole > getByLabelText > getByPlaceholderText > getByText > getByDisplayValue > getByAltText > getByTitle > getByTestId
```

`getByRole` is preferred because it requires correct ARIA semantics, which means tests that pass are also accessible.

## Async patterns — don't use sleep

```ts
// ❌ Wrong — brittle
await new Promise(r => setTimeout(r, 500))
expect(screen.getByText('Loaded')).toBeInTheDocument()

// ✅ Correct — waits for element to appear
expect(await screen.findByText('Loaded')).toBeInTheDocument()

// ✅ Correct — explicit condition
await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

// ✅ Vue / React specific
await flushPromises()  // Vue
await act(async () => { ... })  // React
```

## Mock boundaries — mock at the network, not the module

```ts
// ✅ MSW (recommended for React/Vue/Next.js)
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

const server = setupServer(
  http.get('/api/orders', () => HttpResponse.json(mockOrders))
)

// ✅ When MSW isn't available: mock the fetch/axios module
vi.mock('@/api/orders', () => ({ fetchOrders: vi.fn() }))

// ❌ Don't mock internal components under test — that removes the test's value
vi.mock('./OrderList')  // only if testing the parent's logic independently
```

## Accessibility verification

```ts
// Automated: run axe on rendered output
import { axe } from 'jest-axe'
const { container } = render(<MyComponent />)
const results = await axe(container)
expect(results).toHaveNoViolations()

// Manual checks to document:
// - Tab order through interactive elements
// - Focus visible on all interactive elements
// - Color contrast >= 4.5:1 for text
// - Keyboard operation for custom widgets (dropdowns, modals, tabs)
// - Screen reader announcements for dynamic content (aria-live)
```

## Nondeterminism control

```ts
// Dates — freeze time
vi.useFakeTimers({ now: new Date('2024-01-15T12:00:00Z') })
// ...
vi.useRealTimers()  // restore in afterEach

// Random IDs — mock crypto.randomUUID
vi.spyOn(crypto, 'randomUUID').mockReturnValue('test-uuid')

// Animations — disable in test environment
// Add to vitest setup: window.matchMedia = vi.fn(() => ({ matches: false, ... }))
```

## Snapshot discipline

```ts
// ✅ Acceptable: small, stable, meaningful snapshots
expect(wrapper.find('.badge').text()).toMatchInlineSnapshot(`"New"`)

// ❌ Bad: large DOM tree snapshots — every tiny change breaks the test
expect(wrapper.html()).toMatchSnapshot()

// Update snapshots intentionally, not blindly
// npx vitest run -u  or  npx jest -u
// Always review the diff before committing
```

## Test isolation checklist

- [ ] Store / context reset between tests (`beforeEach` cleanup)
- [ ] Mock handlers reset after each test (`server.resetHandlers()`)
- [ ] Event listeners removed (cleanup in `afterEach` or via RTL's `cleanup`)
- [ ] Global state (window.location, cookies) restored
- [ ] Timers restored (`vi.useRealTimers()`)
