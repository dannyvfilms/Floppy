# Theming

Floppy resolves its colour theme on the server, not in the browser. This page
records the contract, because two of its rules are easy to break by accident and
neither failure is visible in the theme the author has open.

## How a theme is selected

`user.theme` holds a key from `users.appearance.THEME_PRESETS`. The collection
includes the system, light, dark and custom states; Catppuccin Mocha, Dracula,
Nord and Gruvbox classics; OLED, Glass Cinema and Plex-inspired modern themes;
plus Projector and Video Store. `base.html` writes every explicit choice onto
the root element:

```html
<html class="{% if user.theme != 'system' %}{{ user.theme }}{% endif %}">
```

`system` writes no class, which lets the operating system preference decide.

Only `system` follows the operating system preference. Presets and the custom
palette are explicit states. Any token change must be checked in every state.

## Tokens

`src/static/css/input.css` declares the base tokens in four blocks:

| Block | Applies to |
| --- | --- |
| `:root` | the dark defaults |
| `@media (prefers-color-scheme: light) { :root:not(.[every explicit theme]) }` | `system` on a light host |
| `html.light` | an explicit light choice |
| `html.dark` | an explicit dark choice |

The light media selector must exclude every explicit theme class. Otherwise a
light operating system overrides equally specific preset tokens that appear
earlier in the stylesheet. `test_system_light_tokens_exclude_every_explicit_theme`
pins that contract to the preset registry.

Preset classes override the tokens they intentionally change and inherit the
remaining dark defaults. The classic palettes follow their official colour
systems: [Catppuccin](https://python.catppuccin.com/docs/catppuccin/palette.html),
[Dracula](https://github.com/dracula/dracula-theme),
[Nord](https://www.nordtheme.com/) and
[Gruvbox](https://github.com/morhetz/gruvbox). `html.glass` adds a fixed translucent cinema treatment.
`html.custom` inherits the dark defaults; `base.html` adds the six validated
colours plus bounded radius, blur and surface-opacity values as inline variables.
`users.appearance` is the allowlist and validation boundary for those values.

Every explicit preset also owns its shape and motion through
`--theme-radius`, `--motion-duration`, `--motion-distance`, and
`--motion-ease`. Components consume those tokens rather than inventing local
timings or radii, so changing a preset changes the whole interface coherently.
Glass is deliberately soft and fluid, OLED is crisp, and the classic themes
remain restrained.

The global `prefers-reduced-motion: reduce` block is a required safety net. It
must keep navigation and controls usable while reducing animations and smooth
scrolling to effectively instantaneous changes.

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

The header toggle gets every explicit class from `THEME_PRESETS`, removes them,
applies `light` or `dark` immediately, and posts `theme=<value>` alone to the preferences view. That view
therefore reads every field with a
presence check rather than a fallback: a field that defaulted when absent would
be reset on every toggle. `users.tests.views.test_theme_toggle` pins this.

Settings > Appearance owns preset selection, the custom palette, and detail
page composition. It validates the complete payload before saving any part.
Values passed to Django's `json_script` must remain Python dictionaries; the
filter performs the single required serialization before Alpine parses them.

The compact sun/moon switcher is rendered only for the basic `system`, `light`,
and `dark` themes. Presets and custom palettes are changed only from Appearance;
otherwise a single click would silently replace the user's selected design.

`PATCH /api/v1/user/preferences/` follows the same rule and ignores any field
the body omits. It does not currently accept `theme`.
