# React Frontend Adapter

```bash
# 먼저 버전 확인
node -e "console.log(require('./node_modules/react/package.json').version)"
```

## Testing setup

```bash
grep -E "testing-library|vitest|jest|playwright" package.json
```

## Query priority — use the most stable one that works

```tsx
// Most → least stable
getByRole > getByLabelText > getByPlaceholderText > getByText > getByTestId

// getByRole enforces correct ARIA — prefer it
screen.getByRole('button', { name: /submit/i })
screen.getByLabelText('Email address')
screen.getByTestId('submit-btn')  // last resort only
```

## User interaction — userEvent over fireEvent

```tsx
import userEvent from '@testing-library/user-event'

test('submits form', async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn()
  render(<OrderForm onSubmit={onSubmit} />)
  await user.type(screen.getByLabelText('Item'), 'Widget')
  await user.click(screen.getByRole('button', { name: /submit/i }))
  expect(onSubmit).toHaveBeenCalledWith({ item: 'Widget' })
})
```

## Async — findBy* instead of sleep

```tsx
// findBy* = waitFor + getBy
expect(await screen.findByText('Widget A')).toBeInTheDocument()

// explicit condition
await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
```

## Network mocking — MSW over module mocks

```ts
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
const server = setupServer(
  http.get('/api/orders', () => HttpResponse.json([{ id: 1 }]))
)
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```

## State management

```tsx
// Context: wrap in provider
render(<CartProvider><CartSummary /></CartProvider>)

// Zustand: reset between tests
beforeEach(() => useCartStore.setState(initialState))
```

## Accessibility

```tsx
import { axe, toHaveNoViolations } from 'jest-axe'
expect.extend(toHaveNoViolations)
test('accessible', async () => {
  expect(await axe(render(<Modal open />).container)).toHaveNoViolations()
})
```

## Common failure paths

- Missing `key` on list → broken reconciliation
- Stale closure in `useEffect` → missing deps in array
- `value` + `defaultValue` on same input → broken state

---

## Version-specific notes

### React 18+
- StrictMode double-invokes effects — effects must be idempotent
- Automatic batching in async: multiple `setState` in one async callback = one re-render
- `act()` warning on async state → use `findBy*` or `waitFor` instead of manual `act`
- `Suspense` for data fetching is supported (with compatible data libraries)

### React 16 / 17
- No concurrent features — Suspense only for `React.lazy`, not data
- No automatic batching in async callbacks
- `userEvent.setup()` requires `@testing-library/user-event` v14 — check version:
  `node -e "console.log(require('./node_modules/@testing-library/user-event/package.json').version)"`
  If v13 or below, use `userEvent` directly without `.setup()`
