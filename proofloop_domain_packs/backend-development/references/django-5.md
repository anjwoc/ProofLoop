# Django 5 adapter

Confirm whether the project uses Django views, DRF viewsets, forms, or custom service seams before editing. Keep validation in the established serializer/form/model boundary, preserve permission classes and queryset scoping, and check transaction ownership before adding `atomic`. For ORM changes, inspect query count and lazy evaluation where behavior depends on related objects. Run the repository's configured Django test command; do not invent settings or bypass migrations.
