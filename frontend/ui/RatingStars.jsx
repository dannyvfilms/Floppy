import React, { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

/**
 * Shared star row for every rating popup. Presentation and hover/selection only:
 * the surface adapter owns the write, the CSRF token and any popup state.
 * Each star has two halves: the left half picks x.5, the right half the whole star
 * (hover previews the same on the web). Selecting the current value again clears it
 * (`onSelect(null)`). A half star is the lit star clipped to its left half over the
 * unlit one, so `renderStar(lit)` callers need no change.
 */
export function RatingStars({ scaleMax, value, label, renderStar, onSelect, palette, showLabels = true }) {
  const [hover, setHover] = useState(null);
  const [widths, setWidths] = useState({});
  const shown = hover ?? value;
  const has = shown !== null && shown !== undefined;
  // Which half of the star a pointer is over: web reads the DOM box, native uses the touch's local x.
  const pick = (star, event) => {
    const native = event?.nativeEvent ?? event;
    const node = event?.currentTarget;
    const box = node?.getBoundingClientRect?.();
    const clientX = native?.clientX ?? native?.pageX;
    if (box && typeof clientX === 'number') return clientX - box.left < box.width / 2 ? star - 0.5 : star;
    const x = native?.locationX;
    const width = widths[star];
    return width && typeof x === 'number' && x < width / 2 ? star - 0.5 : star;
  };
  const hoverAt = (star, event) => setHover(pick(star, event));
  return <View role="group" accessibilityLabel={label}
    style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}
    onPointerLeave={() => setHover(null)}>
    {Array.from({ length: scaleMax }, (_, index) => {
      const star = index + 1;
      const lit = has && star <= shown;
      const half = has && !lit && star - 0.5 <= shown;
      const width = widths[star];
      return <Pressable key={star} role="button" accessibilityLabel={`${label} ${star}/${scaleMax}`}
        aria-pressed={value !== null && value !== undefined && Math.ceil(value) === star}
        onPress={event => { const next = hover !== null && Math.ceil(hover) === star ? hover : pick(star, event); onSelect(value === next ? null : next); }}
        onHoverIn={event => hoverAt(star, event)}
        onPointerMove={event => hoverAt(star, event)}
        style={({ focused }) => [{ alignItems: 'center' }, focused && palette.focusStyle]}>
        <View onLayout={event => setWidths(current => (current[star] === event.nativeEvent.layout.width
          ? current : { ...current, [star]: event.nativeEvent.layout.width }))}
        style={{ color: lit ? palette.lit : palette.unlit }}>
          {half && width ? <View>
            {renderStar(false)}
            <View style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: width / 2, overflow: 'hidden' }}>
              <View style={{ width, color: palette.lit }}>{renderStar(true)}</View>
            </View>
          </View> : renderStar(lit)}
        </View>
        {showLabels ? <Text style={{ fontSize: 12, marginTop: 4, color: palette.muted }}>{star}</Text> : null}
      </Pressable>;
    })}
  </View>;
}
