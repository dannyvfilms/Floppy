import React, { createContext, useContext } from 'react';
import { Form as SharedForm } from '../ui/controls';

// Provider transport context is separate from app-wide presentation controls.
export const PageContext = createContext(null);
export const usePage = () => useContext(PageContext);

export function Form(props) {
  const { model } = usePage();
  return <SharedForm csrf={model.csrf} returnTo={model.next} {...props} />;
}
