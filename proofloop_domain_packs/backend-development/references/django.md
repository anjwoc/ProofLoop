# Django Backend Adapter

```bash
# 버전 확인
python -m django --version

# 스택 확인
grep -r "pytest-django\|django.test\|factory_boy" requirements*.txt pyproject.toml
grep -r "REST_FRAMEWORK\|INSTALLED_APPS" */settings*.py config/ 2>/dev/null | head -10
grep -E "(test|pytest)" Makefile pyproject.toml setup.cfg 2>/dev/null
```

## Queryset scoping

```python
# Confirm filter doesn't leak across tenants/users
qs = MyModel.objects.filter(owner=user)
assert qs.query.where  # non-empty WHERE clause

# N+1 check
with self.assertNumQueries(1):
    list(Order.objects.select_related("user").filter(status="open"))
```

## Serializer / DRF validation

```python
# Test at the serializer boundary
serializer = MySerializer(data={"field": "bad"})
assert not serializer.is_valid()
assert "field" in serializer.errors

# Write path
serializer = MySerializer(data=valid_payload)
assert serializer.is_valid(), serializer.errors
instance = serializer.save(owner=user)
assert instance.pk is not None

# Auth enforcement
response = api_client.get("/api/private/", HTTP_AUTHORIZATION="")
assert response.status_code == 401
```

## Transaction and atomic

```bash
# Check existing transaction ownership before adding atomic
grep -r "atomic\|ATOMIC_REQUESTS" */views.py */services.py
```

```python
# Test rollback
with pytest.raises(SomeError):
    with transaction.atomic():
        obj = MyModel.objects.create(...)
        raise SomeError()
assert MyModel.objects.filter(pk=obj.pk).count() == 0
```

## Migration checks

```bash
python manage.py makemigrations --check --dry-run  # should output nothing
python manage.py showmigrations | grep -v "\[X\]"  # unapplied
```

Do not squash or delete applied migrations without explicit authorization.

## Common failure paths

1. Invalid input → 400 with field-level errors (not 500)
2. Unauthorized → 401/403 depending on permission class
3. Not found → `get_object_or_404` vs `DoesNotExist` — confirm which is used
4. DB constraint violation → 400, not 500
5. N+1 in list endpoint — add `select_related` / `prefetch_related`

## Anti-patterns

- `MyModel.objects.all()` in a view without `.filter()` — check queryset scope
- Catching every exception and returning success-shaped data
- Mocking queryset when in-memory SQLite can test it directly

---

## Version-specific notes

### Django 5.x
- `LoginRequiredMiddleware` available (was manual before)
- Facets in `ModelAdmin.get_facets()` — new admin feature
- `db_default` field option for database-level defaults

### Django 4.x
- `AsyncToSync` / `SyncToAsync` wrappers more ergonomic
- `StreamingHttpResponse` with async generators supported
- `UniqueConstraint` with `violation_error_message`

### Django 3.x
- No async views support (added in 4.1)
- `path()` converters over `url()` regex (available since 2.0 but common here)
- Check if `django.test.Client` vs `APIClient` (DRF) is used in the test suite
