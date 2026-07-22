# Jest / Vitest Testing Adapter

Use when the repository uses Jest or Vitest. Both share the same API surface; differences are noted explicitly.

## Red-Green workflow

```bash
# Run a single test file first (faster than full suite)
npx jest path/to/orders.test.ts --verbose
# or
npx vitest run path/to/orders.test.ts

# Watch mode during development
npx vitest  # Vitest default
npx jest --watch  # Jest

# The test must FAIL before you implement. If it passes before any code change, the test is wrong.
```

## Mock discipline — three kinds, three use cases

```ts
// 1. Function mock — for callbacks and injected dependencies
const onSubmit = vi.fn()  // or jest.fn()
render(<Form onSubmit={onSubmit} />)
await user.click(submitButton)
expect(onSubmit).toHaveBeenCalledWith({ item: 'Widget' })
expect(onSubmit).toHaveBeenCalledTimes(1)  // not just .called

// 2. Module mock — for API/service layer
vi.mock('@/api/orders', () => ({
  fetchOrders: vi.fn().mockResolvedValue([{ id: 1, item: 'Widget' }])
}))
// ALWAYS reset between tests:
beforeEach(() => vi.clearAllMocks())  // clears call history
// or
afterEach(() => vi.resetAllMocks())   // clears calls + implementation

// 3. Timer mock — for setTimeout/setInterval/Date
vi.useFakeTimers({ now: new Date('2024-01-15') })
// ... test
vi.useRealTimers()  // restore in afterEach
```

## Async — await correctly

```ts
// Promise-returning functions
test('fetches orders', async () => {
  const orders = await fetchOrders()
  expect(orders).toHaveLength(2)
})

// DOM: use findBy* (combines waitFor + getBy)
expect(await screen.findByText('Widget A')).toBeInTheDocument()

// Explicit waitFor — for side effects
await waitFor(() => {
  expect(mockSave).toHaveBeenCalledTimes(1)
})

// ❌ Never: setTimeout in tests
// ❌ Never: await new Promise(r => setTimeout(r, 500))
```

## Snapshot discipline

```ts
// ✅ Inline snapshots — small, reviewable, intentional
expect(formatPrice(10.5)).toMatchInlineSnapshot(`"$10.50"`)

// ❌ Large component HTML snapshots — every unrelated change breaks them
expect(container.innerHTML).toMatchSnapshot()

// When to update:
// npx vitest -u  or  npx jest -u
// Always read the diff before committing — snapshot updates hide real regressions
```

## Spy vs Mock vs Stub

```ts
// Spy — wraps real implementation, just records calls
const spy = vi.spyOn(service, 'save')
await component.submit()
expect(spy).toHaveBeenCalledWith(expectedPayload)
spy.mockRestore()  // important: restore real implementation

// Mock — replaces implementation
vi.spyOn(service, 'save').mockResolvedValue({ id: 42 })

// Stub — fixed return value (use mockReturnValue / mockResolvedValue)
fetchMock.mockResolvedValueOnce({ data: [] })  // returns once, then falls through
```

## Module isolation — what `clearAllMocks` vs `resetAllMocks` vs `restoreAllMocks` does

| Method | Clears calls | Resets implementation | Restores spies |
|---|---|---|---|
| `clearAllMocks` | ✅ | ❌ | ❌ |
| `resetAllMocks` | ✅ | ✅ | ❌ |
| `restoreAllMocks` | ✅ | ✅ | ✅ |

Put the right one in `afterEach`. If unsure, use `restoreAllMocks` + re-declare mocks in `beforeEach`.

## Environment setup (vitest)

```ts
// vitest.config.ts
export default defineConfig({
  test: {
    environment: 'jsdom',    // for DOM tests
    // environment: 'node',  // for pure logic/API
    globals: true,           // no need to import expect, vi, etc.
    setupFiles: ['./src/test/setup.ts'],
    clearMocks: true,        // automatically clearAllMocks between tests
  }
})

// src/test/setup.ts
import '@testing-library/jest-dom'  // extends expect with toBeInTheDocument etc.
```

## Coverage — use as a locator, not a target

```bash
# Focus coverage on the module you changed
npx vitest run --coverage --reporter=verbose src/orders/

# Find untested branches specifically
npx jest --coverage --collectCoverageFrom="src/orders/**" --coverageReporters=text

# Don't chase 100% — cover behavior boundaries, not every line
```

## Anti-patterns

- `expect(fn).toBeCalled()` — too weak; use `toHaveBeenCalledWith(args)`
- `jest.mock()` at test body level (not module level) — order-dependent, unpredictable
- Sharing mutable state in `describe`-level `let` without resetting in `beforeEach`
- Using `--forceExit` to hide async leaks — find and fix the leak instead
- `setTimeout` in test code — use fake timers or `findBy*`
