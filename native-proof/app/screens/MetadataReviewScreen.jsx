import React from 'react';
import { Screen } from '../components/Screen';
import MetadataReviewSlot from '../surfaces/MetadataReviewSlot';

export default function MetadataReviewScreen({ navigate }) {
  return <Screen title="Episode ordering and provider moves"
    subtitle="Review viewings, move a show between providers, and pick metadata matches">
    <MetadataReviewSlot navigate={navigate} />
  </Screen>;
}
