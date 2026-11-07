import React, { useLayoutEffect, useRef, useState } from 'react';

// Browser height reveal matching the release sidebar animation. The native
// counterpart renders the same children without owning DOM APIs.
export function Reveal({ open, children, duration = 200 }) {
  const nodeRef = useRef(null);
  const changed = useRef(false);
  const [visible, setVisible] = useState(open);

  useLayoutEffect(() => {
    if (!changed.current) {
      changed.current = true;
      setVisible(open);
      return undefined;
    }
    const node = nodeRef.current;
    if (!node) return undefined;
    if (open) {
      setVisible(true);
      const frame = requestAnimationFrame(() => {
        const target = nodeRef.current;
        if (!target) return;
        const height = target.scrollHeight;
        target.style.overflow = 'hidden';
        const animation = target.animate(
          [{ height: '0px' }, { height: `${height}px` }],
          { duration, easing: 'ease-in-out' },
        );
        animation.onfinish = () => {
          target.style.height = '';
          target.style.overflow = '';
        };
      });
      return () => cancelAnimationFrame(frame);
    }
    const height = node.scrollHeight;
    node.style.overflow = 'hidden';
    const animation = node.animate(
      [{ height: `${height}px` }, { height: '0px' }],
      { duration, easing: 'ease-in-out' },
    );
    animation.onfinish = () => {
      node.style.height = '';
      node.style.overflow = '';
      setVisible(false);
    };
    return undefined;
  }, [open, duration]);

  return <div ref={nodeRef} style={{ display: visible ? 'block' : 'none', overflow: 'hidden' }}>{children}</div>;
}
