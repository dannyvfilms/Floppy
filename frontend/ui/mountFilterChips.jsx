import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { FilterChips } from './controls';

// The page's Alpine scope owns the selection (selectedMedia) and the switch
// (switchMedia); mirror it instead of keeping a second copy.
function Chips({ host, props }) {
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    const Alpine = window.Alpine;
    if (!Alpine) return undefined;
    const runner = Alpine.effect(() => setSelected(Alpine.$data(host).selectedMedia));
    return () => Alpine.release(runner);
  }, [host]);
  return <FilterChips items={props.items} label={props.label} selected={selected}
    onSelect={(value) => window.Alpine?.$data(host).switchMedia(value)} />;
}

export function mountFilterChips(host, props) {
  return mountRoot(host, <Chips host={host} props={props} />);
}
