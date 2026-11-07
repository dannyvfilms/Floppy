import React, { useEffect, useState } from 'react';
import { DetailView } from '../../../frontend/pages/DetailView';
import { Screen } from '../components/Screen';
import { createDetailModelForItem, loadDetailModel } from '../surfaces/DetailSlot';
import { palette } from '../theme';

export default function DetailScreen({ params, onBack }) {
  const item = params?.item;
  const [model, setModel] = useState(() => createDetailModelForItem(item));
  const [loading, setLoading] = useState(Boolean(item));
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!item) {
      setLoading(false);
      setModel(createDetailModelForItem(null));
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    loadDetailModel(item).then(next => {
      if (cancelled) return;
      setModel(next);
      setLoading(false);
    }).catch(cause => {
      if (cancelled) return;
      setModel(createDetailModelForItem(item));
      setError(cause?.message || 'The detail could not be loaded from the server.');
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [item, attempt]);

  return <Screen onBack={onBack}>
    <DetailView
      model={model}
      labels={model.labels}
      palette={palette}
      loading={loading}
      error={error}
      onRetry={item ? () => setAttempt(value => value + 1) : undefined}
    />
  </Screen>;
}