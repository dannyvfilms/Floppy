import React from 'react';
import App from '../../App';
import RailPreview from './rail-preview';

export default function Index() {
  return process.env.EXPO_PUBLIC_RAIL_PREVIEW === '1' ? <RailPreview /> : <App />;
}
