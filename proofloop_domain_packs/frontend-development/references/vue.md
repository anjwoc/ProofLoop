# Vue Frontend Adapter

```bash
# 버전 확인
node -e "console.log(require('./node_modules/vue/package.json').version)"
grep -E "pinia|vuex" package.json  # state management
```

## Component testing

```ts
import { mount } from '@vue/test-utils'
// Prefer mount() over shallowMount() — stubs hide real failures

test('emits submit with data', async () => {
  const wrapper = mount(OrderForm)
  await wrapper.find('input[name="item"]').setValue('Widget')
  await wrapper.find('button[type="submit"]').trigger('click')
  expect(wrapper.emitted('submit')?.[0][0]).toEqual({ item: 'Widget' })
})
```

## Async — wait for DOM updates

```ts
import { flushPromises } from '@vue/test-utils'

test('shows data after fetch', async () => {
  vi.mock('@/api/orders', () => ({ fetchOrders: vi.fn().mockResolvedValue([{ id: 1 }]) }))
  const wrapper = mount(OrderList)
  await flushPromises()
  expect(wrapper.text()).toContain('Widget')
})
```

## State management

```ts
// Pinia — fresh store per test (required)
import { setActivePinia, createPinia } from 'pinia'
beforeEach(() => setActivePinia(createPinia()))

// Component test with store
import { createTestingPinia } from '@pinia/testing'
mount(CartSummary, {
  global: { plugins: [createTestingPinia({ initialState: { cart: { items: [] } } })] }
})
```

## Composable testing

```ts
import { useOrderValidation } from '@/composables/useOrderValidation'

test('validates required field', () => {
  const { validate, errors } = useOrderValidation()
  validate({ item: '' })
  expect(errors.value.item).toBeTruthy()
})
```

## Router in tests

```ts
import { createRouter, createMemoryHistory } from 'vue-router'
const router = createRouter({ history: createMemoryHistory(), routes })
mount(App, { global: { plugins: [router] } })
await router.isReady()
```

## Common failure paths

- `reactive()` vs `ref()`: accessing `.value` on `reactive()` = no-op
- `v-if` removes from DOM — `queryByText` returns null; `v-show` leaves it hidden
- Scoped style class names change with hash — assert behavior, not class names

---

## Version-specific notes

### Vue 3 (Composition API)
- `setup()` / `<script setup>` — composables are plain functions, testable directly
- `defineModel()` (3.4+) for two-way binding: test via `modelValue` prop + `onUpdate:modelValue`
- Pinia replaces Vuex — prefer `createTestingPinia` from `@pinia/testing`
- `@vue/test-utils` v2 required

### Vue 2 (Options API)
- `@vue/test-utils` v1 syntax — `wrapper.vm.$data`, `wrapper.vm.$emit`
- Vuex store: create a fresh store instance per test

```ts
// Vue 2 test pattern
import { shallowMount, createLocalVue } from '@vue/test-utils'
import Vuex from 'vuex'
const localVue = createLocalVue()
localVue.use(Vuex)
const store = new Vuex.Store({ state: { items: [] } })
const wrapper = shallowMount(CartSummary, { localVue, store })
```
