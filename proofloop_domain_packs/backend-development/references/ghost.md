# Ghost Backend Adapter

```bash
# 버전 확인
cat package.json | grep '"version"'
ls core/server/api/ 2>/dev/null || ls ghost/core/core/server/api/
grep -E "(test|jest|mocha)" package.json | head -5
```

## API surface — know which one you're touching

- **Admin API** (`/ghost/api/admin/`): Bearer token required, CMS operations
- **Content API** (`/ghost/api/content/`): public, key-authenticated, read-only

```bash
# Trace endpoint to controller
grep -r "router.get\|router.post" core/server/api/ --include="*.js" | grep "posts"
# Find matching test
find test/ -name "*posts*" | grep -v node_modules
```

## Webhook behavior — async, don't assert immediately

```javascript
// Test event emission, not HTTP delivery
const events = require('@tryghost/events')
sinon.spy(events, 'emit')
await api.posts.edit(postData, frameOptions)
assert(events.emit.calledWith('post.edited'))
```

## Theme validation

```bash
npx gscan path/to/theme --verbose
```

## Common failure paths

1. **Missing `frame` fields**: Ghost passes `frame` (context + options + data) to controllers — verify `frame.options` has required fields
2. **Permission model**: `canThis(user).edit.post(post)` — test that non-admin is rejected
3. **Settings cache**: `settingsCache.get('key')` may be stale in tests — reset between cases
4. **`labs` flags**: features gated by `isSet('featureFlag')` — check before testing new behavior

---

## Version-specific notes

### Ghost 5.x
- Native Content API v3 (previous v2 deprecated)
- Members and tiers API
- Bookshelf.js ORM — check model file for field definitions, don't assume

### Ghost 4.x and below
- Content API v2 still primary
- Custom integrations via webhooks; portal features limited
