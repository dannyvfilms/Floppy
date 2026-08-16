# Test accounts

Floppy has an explicit `User.is_test_account` flag for disposable, QA, and
automation users. Accounts with this flag are excluded from normal user
pickers, including Plex webhook sharing. The flag is independent of Plex
configuration and import history, so real users remain selectable whether or
not they have connected Plex.

When creating a test account in code, use the dedicated manager helper:

```python
User.objects.create_test_user(username="fixture-user")
```

The helper always sets `is_test_account=True`. Code that creates an ordinary
user with `create_user()` remains an ordinary user unless it explicitly passes
`is_test_account=True`.

For manually created QA accounts, set **Test account** in the Django admin.
The migration that introduced this flag also marks the existing QA accounts
identified during the Plex sharing work. The migration's backfill is a
one-time data repair; new test accounts should use the explicit flag rather
than relying on username conventions.
