import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import { View } from 'react-native';

/**
 * Universal form contract.
 *
 * The legacy Form in `frontend/ui/controls.jsx` renders a real `<form>`, writes
 * the CSRF token and return URL into hidden inputs and uses the browser's
 * confirmation dialog. That shape only works in a browser. This module keeps
 * the same form metadata but is transport-neutral: it renders a React Native
 * `View`, collects values from nested fields, and leaves the POST itself to the
 * host.
 *
 * The contract:
 *   - `Form` renders the RN container and supplies `FormProvider`.
 *   - `FormProvider` owns the values and calls `onSubmit` with
 *     `{ action, csrf, returnTo, values, event }`.
 *   - `useForm` lets nested fields read the metadata and update values without
 *     threading props through every level.
 *
 * Adapter note (browser POST / native transport):
 *   This file never submits by itself and never touches browser globals, DOM
 *   APIs or hidden inputs. The host supplies the transport:
 *
 *   Browser adapter
 *     Render the contract inside a real `<form method="post" action=… encType=…>`
 *     and forward the native submit event to `submit(event)`. When it receives
 *     an event, the universal submit prevents the browser's default submission
 *     because transport belongs to `onSubmit`. The adapter still owns the hidden
 *     `csrfmiddlewaretoken` / `next` inputs and the confirm presentation (the
 *     browser's confirm dialog). If the adapter lets the browser POST instead of
 *     calling `onSubmit`, it should use its own browser form implementation
 *     rather than this universal `submit`.
 *
 *   Native adapter (iOS / Android)
 *     Call `submit()` from the save button or keyboard handler, then send the
 *     collected `values` plus `action`, `csrf`, `returnTo` and `encType` through
 *     the app's network layer. Supply `onConfirm` (using `Alert` or a shared
 *     dialog) so confirmation runs before `onSubmit`.
 *
 *   Confirmation is only performed when a handler is available: pass a
 *   `confirm` function or an `onConfirm(message)` callback. A confirm message
 *   without a handler is blocked rather than silently bypassed. Confirmation
 *   handlers may return a boolean or a Promise<boolean>.
 *
 * The form id is available to adapters through context. It is also applied as
 * `nativeID` on the RN container so web accessibility and label associations
 * keep working; a browser adapter that renders its own `<form>` should avoid
 * duplicating the same id.
 */

export const FormContext = createContext(null);

const EMPTY_VALUES = {};

/**
 * Provides form metadata and values to nested fields. The provider renders no
 * platform element; wrap it in a `View` yourself or use `Form`.
 *
 * `defaultValues` is read once when the provider mounts. Nested fields call
 * `setValue(name, value)` to update the collected values. `getValue(name)` also
 * falls back to values registered with `registerField`.
 */
export function FormProvider({
  action,
  csrf,
  returnTo,
  id,
  encType,
  confirm,
  defaultValues = EMPTY_VALUES,
  onSubmit,
  onConfirm,
  children,
}) {
  const [values, setValuesState] = useState(() => ({ ...defaultValues }));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const valuesRef = useRef(values);
  valuesRef.current = values;
  const submittingRef = useRef(false);
  const registeredRef = useRef({});
  const propsRef = useRef({
    action,
    csrf,
    returnTo,
    id,
    encType,
    confirm,
    onSubmit,
    onConfirm,
  });
  propsRef.current = {
    action,
    csrf,
    returnTo,
    id,
    encType,
    confirm,
    onSubmit,
    onConfirm,
  };

  const setValue = useCallback((name, value) => {
    const current = valuesRef.current;
    const next = {
      ...current,
      [name]: typeof value === 'function' ? value(current[name]) : value,
    };
    valuesRef.current = next;
    setValuesState(next);
  }, []);

  const setValues = useCallback(next => {
    const current = valuesRef.current;
    const nextValues = {
      ...current,
      ...(typeof next === 'function' ? next(current) : next),
    };
    valuesRef.current = nextValues;
    setValuesState(nextValues);
  }, []);

  const getValue = useCallback(name => (
    Object.prototype.hasOwnProperty.call(valuesRef.current, name)
      ? valuesRef.current[name]
      : registeredRef.current[name]
  ), []);

  /**
   * Optional convenience for dynamic fields. Registration stores a default in a
   * ref so it can be called during render without a render-phase state update;
   * the default is included in `getValue` and in the submitted values. Call
   * `setValue` for a value that must be reflected by the reactive `values`.
   */
  const registerField = useCallback((name, defaultValue = '') => {
    if (!Object.prototype.hasOwnProperty.call(registeredRef.current, name)) {
      registeredRef.current = { ...registeredRef.current, [name]: defaultValue };
    }
    return {
      name,
      defaultValue,
      getValue: () => getValue(name),
      setValue: value => setValue(name, value),
    };
  }, [getValue, setValue]);

  const submit = useCallback(async event => {
    // The contract delegates transport to onSubmit; a supplied event must not
    // also trigger a native form submission.
    event?.preventDefault?.();

    if (submittingRef.current) return false;
    const form = propsRef.current;
    if (typeof form.onSubmit !== 'function') return false;

    submittingRef.current = true;
    setIsSubmitting(true);
    try {
      const message = typeof form.confirm === 'string' ? form.confirm : '';
      const handler = typeof form.confirm === 'function' ? form.confirm : form.onConfirm;

      if (message || typeof form.confirm === 'function') {
        if (typeof handler !== 'function') {
          // Do not let a requested confirmation be bypassed silently.
          return false;
        }
        const approved = await (message ? handler(message) : handler());
        if (!approved) return false;
      }

      const submittedValues = { ...registeredRef.current, ...valuesRef.current };
      const result = await form.onSubmit({
        action: form.action,
        csrf: form.csrf,
        returnTo: form.returnTo,
        encType: form.encType,
        values: submittedValues,
        event,
      });
      return result !== false;
    } finally {
      submittingRef.current = false;
      setIsSubmitting(false);
    }
  }, []);

  const context = useMemo(() => ({
    action,
    csrf,
    returnTo,
    id,
    encType,
    confirm,
    values,
    setValue,
    setValues,
    getValue,
    registerField,
    submit,
    isSubmitting,
  }), [
    action,
    csrf,
    returnTo,
    id,
    encType,
    confirm,
    values,
    setValue,
    setValues,
    getValue,
    registerField,
    submit,
    isSubmitting,
  ]);

  return <FormContext.Provider value={context}>{children}</FormContext.Provider>;
}

export function useForm() {
  const context = useContext(FormContext);
  if (!context) {
    throw new Error('useForm must be used inside a Form or FormProvider.');
  }
  return context;
}

/**
 * Universal form surface. It renders an RN `View` rather than a `<form>` and
 * accepts the legacy form metadata. Transport remains the host's responsibility
 * (see the adapter note above).
 */
export function Form({
  action,
  csrf,
  returnTo,
  id,
  encType,
  confirm,
  onSubmit,
  onConfirm,
  defaultValues,
  children,
  style,
  testID,
  accessibilityLabel,
  ...viewProps
}) {
  return <FormProvider
    action={action}
    csrf={csrf}
    returnTo={returnTo}
    id={id}
    encType={encType}
    confirm={confirm}
    defaultValues={defaultValues}
    onSubmit={onSubmit}
    onConfirm={onConfirm}>
    <View
      nativeID={id}
      style={style}
      testID={testID}
      accessibilityLabel={accessibilityLabel}
      {...viewProps}>
      {children}
    </View>
  </FormProvider>;
}
