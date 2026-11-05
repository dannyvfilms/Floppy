import React, { useState } from 'react';
import { Linking } from 'react-native';
import { Screen, Section } from '../components/Screen';
import ArtworkSlot from '../surfaces/ArtworkSlot';
import DetailChildrenSlot from '../surfaces/DetailChildrenSlot';
import DetailRelatedSlot from '../surfaces/DetailRelatedSlot';
import DetailSlot from '../surfaces/DetailSlot';
import DetailTrackingSlot from '../surfaces/DetailTrackingSlot';
import { CheckInStateSlot } from '../surfaces/PlaybackSlot';
import NotesSlot from '../surfaces/NotesSlot';
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
    <Section title="Check-in">
      <CheckInStateSlot />
    </Section>
    <Section title="Tracking">
      <DetailTrackingSlot target={trackTarget} onOpen={setTrackTarget}
        onClose={() => setTrackTarget(null)} />
    </Section>
    <Section title="Your notes">
      <NotesSlot />
    </Section>
    <Section title="Artwork and editions">
      <ArtworkSlot />
    </Section>
    <Section title="Seasons, episodes and issues">
      <DetailChildrenSlot onTrack={setTrackTarget} />
    </Section>
    <Section title="Related media">
      <DetailRelatedSlot onOpenExternal={url => { Linking.openURL(url).catch(() => {}); }} />
    </Section>
  </Screen>;
}
