import { createContext } from 'react';

// A platform adapter supplies the hook that reports how far the keyboard covers the bottom of the
// window (the native keyboard, or the web visual viewport), the same way GlobalSearch takes it as a
// prop. Without an adapter nothing is covered. Shared menus read it from here instead of each taking a prop.
export const KeyboardOverlapContext = createContext(() => 0);
