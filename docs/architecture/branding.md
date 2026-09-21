# Branding

Authenticated users choose one navigation identity in Settings > Appearance:
the original colour logo, the monochrome logo, an editable text wordmark, a
custom image, or a visually hidden logo. Changes reach the sidebar only after
Save appearance. The editor labels unsaved image and text changes as a preview.
The shared `users/components/brand_logo.html` template is the single renderer
used by the authenticated shell, public shell, and sign-in layout.

Hidden branding keeps a labelled home link for keyboard and screen-reader
users. Text is escaped by Django. New names are limited to 20 characters so
they cannot take over the sidebar. Previously saved longer names remain intact;
the sidebar header grows rather than covering its navigation.

Wordmarks have local font, size, weight, spacing, and fill controls. A theme
gradient uses the active theme's text and accent colours; the Glass cinema
theme retains its existing white, cyan, and lavender treatment. Custom solid
and gradient modes accept only six-digit hexadecimal colours. The same
validated values render in the editor and navigation.

Custom images accept PNG, JPEG, and WebP uploads up to 2 MB. They are decoded,
resized within 256 by 64 pixels, and re-encoded as metadata-free WebP before
storage. SVG is intentionally rejected. The resulting data URL is capped at
40 KB so a user preference cannot become an unbounded page payload.

The built-in sidebar mark keeps its original 158 by 48 pixel display size and
does not shrink as a flex item. Custom marks share the same 48 pixel height and
fit within the sidebar width.

Anonymous visitors have no user preference. The sign-in and other public
pages therefore use the original Floppy logo until a superuser explicitly
publishes a copy of their saved branding. Publishing copies only display
fields to `ApplicationSettings.public_branding`; later personal edits do not
change the public page. The admin can restore the original logo. Malformed
stored snapshots fall back to the original logo, and other signed-in users
continue to see their own preferences.
