# Next.js Frontend Adapter

```bash
# 버전 확인
node -e "console.log(require('./node_modules/next/package.json').version)"
# 라우터 확인
ls app/ 2>/dev/null && echo "App Router" || echo "Pages Router"
```

## Test setup

```bash
grep -E "jest|vitest|@testing-library" package.json
cat jest.config.ts vitest.config.ts 2>/dev/null | head -20
```

## Route Handler / API testing

```ts
// App Router (app/api/orders/route.ts)
import { NextRequest } from 'next/server'
import { GET } from '@/app/api/orders/route'

test('returns orders', async () => {
  const req = new NextRequest('http://localhost/api/orders')
  const res = await GET(req)
  expect(res.status).toBe(200)
  const data = await res.json()
  expect(Array.isArray(data)).toBe(true)
})
```

## Server Component testing

```tsx
// Server Components: call as async function, render the result
global.fetch = vi.fn().mockResolvedValue({
  ok: true, json: () => Promise.resolve([{ id: 1 }])
})
const page = await OrdersPage()  // async component
const { getByText } = render(page)
expect(getByText('Widget')).toBeInTheDocument()
```

## Client Component testing

```tsx
'use client'
// Same as React — use @testing-library/react
// Confirm with 'use client' directive at top of file
```

## Middleware testing

```ts
import { middleware } from '@/middleware'
const req = new NextRequest('http://localhost/admin/stats')
const res = await middleware(req)
expect(res.status).toBe(307)  // redirect expected
```

## Data fetching — confirm caching strategy

```tsx
// Always-fresh (SSR)
fetch('/api/orders', { cache: 'no-store' })

// ISR
fetch('/api/orders', { next: { revalidate: 60 } })

// Tests: always mock fetch — never hit real APIs
```

## Hydration mismatch guard

```tsx
// Guard browser-only APIs
typeof window !== 'undefined' ? window.localStorage : null
// Or: useEffect(() => { /* client-only */ }, [])
```

## Common failure paths

- `useRouter` in Server Component → crash (Client Component only)
- `cookies()` / `headers()` called in module scope → error (must be inside request)
- Missing `loading.tsx` → blank flash on slow data
- `next/image` without `alt` → a11y error + build warning

## Build and type check

```bash
npx next build 2>&1 | tail -20   # catches import and type errors
npx tsc --noEmit                  # faster, no bundle
```

---

## Version-specific notes

### Next.js 14+ (App Router default)
- `app/` directory with layouts, loading, error, not-found as first-class files
- Server Components by default — add `'use client'` only when you need hooks or browser APIs
- Route Handlers replace API Routes (`app/api/.../route.ts`)
- `defineModel` and new form actions via `useFormState` / `useFormStatus`

### Next.js 12/13 (Pages Router or hybrid)
- `pages/api/` for API routes — test with `createMocks` from `node-mocks-http`
- `getServerSideProps` / `getStaticProps` are testable as plain functions
- `next/router` (not `next/navigation`) for routing

```ts
// Pages Router API route test
import { createMocks } from 'node-mocks-http'
import handler from '@/pages/api/orders'

test('GET returns orders', async () => {
  const { req, res } = createMocks({ method: 'GET' })
  await handler(req, res)
  expect(res._getStatusCode()).toBe(200)
})
```
