import React, { useState } from 'react';
import { Linking } from 'react-native';
import { DetailView } from '../../../frontend/pages/DetailView';
import { Screen } from '../components/Screen';
import ArtworkSlot from '../surfaces/ArtworkSlot';
import DetailChildrenSlot from '../surfaces/DetailChildrenSlot';
import DetailRelatedSlot from '../surfaces/DetailRelatedSlot';
import DetailTrackingSlot from '../surfaces/DetailTrackingSlot';
import { CheckInStateSlot } from '../surfaces/PlaybackSlot';
import { createDetailModel } from '../surfaces/DetailSlot';
import NotesSlot from '../surfaces/NotesSlot';
import ProgressSlot from '../surfaces/ProgressSlot';
import RatingSlot from '../surfaces/RatingSlot';
import { palette } from '../theme';

export default function DetailScreen({ params, onBack }) {
  const [trackTarget, setTrackTarget] = useState(null);
  const [actionStatus, setActionStatus] = useState('');
  const model = createDetailModel();
  const actions = model.actions || {};
  model.actions = {
    primary: actions.primary
      ? { ...actions.primary, label: actionStatus || actions.primary.label,
        onPress: () => setActionStatus('Watching episode 7') }
      : null,
    items: (actions.items || []).map(item => ({ ...item,
      onPress: () => setActionStatus('In your library') })),
  };

  return <Screen onBack={onBack}>
    <DetailView
      model={model}
      labels={model.labels}
      palette={palette}
      sectionBodies={{
        score: <RatingSlot />,
        progress: <ProgressSlot />,
        'check-in': <CheckInStateSlot />,
        tracking: <DetailTrackingSlot target={trackTarget} onOpen={setTrackTarget}
          onClose={() => setTrackTarget(null)} />,
        notes: <NotesSlot />,
        artwork: <ArtworkSlot />,
        children: <DetailChildrenSlot onTrack={setTrackTarget} />,
        related: <DetailRelatedSlot onOpenExternal={url => { Linking.openURL(url).catch(() => {}); }} />,
      }} />
  </Screen>;
}
