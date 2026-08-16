# Theming

Floppy resolves its colour theme on the server, not in the browser. This page
records the contract, because two of its rules are easy to break by accident and
neither failure is visible in the theme the author has open.

## How a theme is selected

`user.theme` holds one of `light`, `dark` or `system`. `base.html` writes the
value onto the root element:

```html
<html class="{% if user.theme == 'light' %}light{% elif user.theme == 'dark' %}dark{% endif %}">
```

`system` writes no class, which lets the operating system preference decide.

There are therefore six states, not two: three values of `user.theme` crossed
with a light or dark operating system preference. Any change to colour must hold
in all six.

## Tokens

`src/static/css/input.css` declares every `--color-*` token in four blocks:

| Block | Applies to |
| --- | --- |
| `:root` | the dark defaults |
| `@media (prefers-color-scheme: light) { :root:not(.dark) }` | `system` on a light host |
| `html.light` | an explicit light choice |
| `html.dark` | an explicit dark choice |

`html.dark` repeats the `:root` values. That repetition is redundant, since
`:root` already carries the dark values and the light media query is guarded by
`:not(.dark)`. It is kept only so the four blocks read symmetrically. If you add
a token, add it to `:root`, to the media query and to `html.light`; the
`html.dark` copy is optional and must match `:root` if you write it.

## Never use Tailwind's `dark:` variant

`dark:` compiles to `@media (prefers-color-scheme: dark)`, which reads the
operating system and ignores `user.theme`. It agrees with the app only while a
user keeps the system default, and inverts for anyone who overrides it. Use a
token instead.

`src/app/tests/test_theme_tokens.py` fails the build on any `dark:` utility in a
template, and on the raw palette utilities that have token equivalents.

## Colour on a fixed surface

A token resolves per theme; a hardcoded colour does not. Pairing them inverts.

- A `--color-*` text token on a permanently dark surface, such as a poster
  overlay (`bg-gray-900/90`) or a toast (`bg-red-700/95`), goes dark-on-dark in
  the light theme. Pin a literal foreground there instead, usually `text-white`.
- A hardcoded light foreground on a token surface fails the other way.

Toast icons are the standard example of the first case and keep their literal
palette values on purpose.

## Two values that must stay apart

`--color-hover-dim` is painted over `--color-sidebar` by the sidebar navigation
and the header controls. If the two resolve to the same colour, those controls
lose their hover feedback. They collided at `#f1f3f5` in the light theme once
already.

## Rebuilding `main.css`

```bash
npx @tailwindcss/cli -i ./src/static/css/input.css -o ./src/static/css/main.css
```

The input uses `source("../../")`, so the build scans `src/`, which contains its
own committed output. One pass is not a fixpoint: a class removed from a
template can survive in the stylesheet because the previous stylesheet still
mentions it. Run the command until the output stops changing.

For the same reason, a Python or JavaScript file that contains a Tailwind class
name as a string literal will have that class compiled into the stylesheet. The
banned-utility list in `test_theme_tokens.py` assembles its names from
concatenated parts to avoid exactly that.

## Persisting a theme change

The header toggle flips the root class immediately and posts `theme=<value>`
alone to the preferences view. That view therefore reads every field with a
presence check rather than a fallback: a field that defaulted when absent would
be reset on every toggle. `users.tests.views.test_theme_toggle` pins this.

`PATCH /api/v1/user/preferences/` follows the same rule and ignores any field
the body omits. It does not currently accept `theme`.
