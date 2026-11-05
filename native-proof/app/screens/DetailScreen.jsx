import React from 'react';
import { Screen, Section } from '../components/Screen';
import DetailChildrenSlot from '../surfaces/DetailChildrenSlot';
import DetailTrackingSlot from '../surfaces/DetailTrackingSlot';
import DetailSlot from '../surfaces/DetailSlot';
import ProgressSlot from '../surfaces/ProgressSlot';
import RatingSlot from '../surfaces/RatingSlot';

export default function DetailScreen({ params, onBack }) {
  const title = params?.item?.title || 'Detail';
  return <Screen title={title} subtitle="Detail, tracking and rating" onBack={onBack}>
    <DetailSlot />
    <Section title="Your score">
      <RatingSlot />
    </Section>
    <Section title="Your progress">
      <ProgressSlot />
    </Section>
    <Section title="Tracking">
      <DetailTrackingSlot />
    </Section>
    <Section title="Seasons, episodes and issues">
      <DetailChildrenSlot />
    </Section>
  </Screen>;
}
