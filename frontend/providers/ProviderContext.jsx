import React, { createContext, useContext, useMemo } from 'react';

// Transport-neutral provider-page context. The web mount supplies navigation,
// form submission and URL intents; native screens can supply their own adapters.
export const ProviderContext = createContext(null);

export function useProvider() {
  return useContext(ProviderContext) || {};
}

export function ProviderProvider({
  model,
  labels,
  onOpenUrl,
  onSubmit,
  onNavigate,
  palette,
  buttonPalette,
  renderIcon,
  children,
}) {
  const value = useMemo(() => ({
    model,
    labels: labels || model?.labels || {},
    t: text => (labels || model?.labels || {})[text] ?? text,
    onOpenUrl,
    onSubmit,
    onNavigate,
    palette,
    buttonPalette,
    renderIcon,
  }), [model, labels, onOpenUrl, onSubmit, onNavigate, palette, buttonPalette, renderIcon]);
  return React.createElement(ProviderContext.Provider, { value }, children);
}
