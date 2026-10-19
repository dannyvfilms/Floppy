# iPhone Duo layout reference

Use these names when discussing layouts and naming screenshots. Dimensions are
browser viewport sizes in CSS pixels, excluding the simulator frame.

| Layout | Screen and orientation | Reference viewport |
| --- | --- | --- |
| Duo Closed Portrait | Outer screen, upright | Not yet confirmed |
| Duo Closed Landscape | Outer screen, horizontal | 696 × 464 |
| Duo Open Portrait | Inner screen, vertical | 696 × 976 |
| Duo Open Landscape | Inner screen, horizontal | 976 × 696 |

Add **Camera Left** or **Camera Right** to distinguish the two closed landscape
rotations. Add **Status Left** or **Status Right** when the position of the iOS
status controls matters on the open screen. For example:

- Duo Closed Landscape — Camera Right
- Duo Open Portrait — Status Right

## Layout expectations

- Closed Landscape shows the top portion of Open Portrait at the same width.
  Media details keep the same backdrop and logo geometry as the taller view;
  metadata and actions remain farther down the scrollable page.
- Leave space below the logo before the fold or bottom edge.
- Keep navigation and iOS status controls on the same row. Respect a camera
  inset on the left; a bottom-right camera does not require extra right padding
  in the top navigation. Content still respects its safe-area insets.
- Use available width for compact information rows and left-aligned cards.
  A shorter viewport should not make the cards taller.
- Check all three confirmed viewports, both closed landscape rotations, and
  desktop widths when changing shared responsive styles. Desktop checks should
  account for the space taken by the sidebar.
- Browser resizing validates layout geometry. Native camera and status insets
  also require simulator checks or explicit inset emulation.
