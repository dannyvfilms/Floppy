import React, { useState } from 'react';
import { Screen, Section } from '../components/Screen';
import DetailChildrenSlot from '../surfaces/DetailChildrenSlot';
import DetailSlot from '../surfaces/DetailSlot';
import DetailTrackingSlot from '../surfaces/DetailTrackingSlot';
import ProgressSlot from '../surfaces/ProgressSlot';
import RatingSlot from '../surfaces/RatingSlot';

export default function DetailScreen({ params, onBack }) {
  const title = params?.item?.title || 'Detail';
  const [trackTarget, setTrackTarget] = useState(null);
  return <Screen title={title} subtitle="Detail, tracking and rating" onBack={onBack}>
    <DetailSlot />
    <Section title="Your score">
      <RatingSlot />
    </Section>
    <Section title="Your progress">
      <ProgressSlot />
    </Section>
    <Section title="Tracking">
      <DetailTrackingSlot target={trackTarget} onOpen={setTrackTarget}
        onClose={() => setTrackTarget(null)} />
    </Section>
    <Section title="Seasons, episodes and issues">
      <DetailChildrenSlot onTrack={setTrackTarget} />
    </Section>
  </Screen>;
}
