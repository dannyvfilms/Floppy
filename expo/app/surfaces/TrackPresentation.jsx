import React, { useMemo } from 'react';
import { View } from 'react-native';
import { AdaptivePresentationSheet } from '../components/AdaptivePresentationSheet';
import { trackTabItems } from '../../../frontend/ui/TrackFormTabs';

// Every Tracking section, in order, with the SF Symbol for its rail button.
const SECTIONS = [
  { value: 'general', label: 'General', icon: 'pencil' },
  { value: 'tags', label: 'Tags', icon: 'tag' },
  { value: 'metadata', label: 'Metadata', icon: 'doc.text' },
  { value: 'collection', label: 'Collection', icon: 'square.stack.3d.up' },
  { value: 'plays', label: 'Plays', icon: 'play.circle' },
  { value: 'status-history', label: 'Status history', icon: 'clock.arrow.circlepath' },
  { value: 'discover', label: 'Discover', icon: 'sparkles' },
];

// Always the full section list, so the rail has the same items from the first frame: adding
// toolbar items while the sheet is open drops the touch handler of the sheet's body (see
// SheetHost.ios.jsx). Loaded tabs only supply their labels ("Episode plays").
export function trackRailItems(tabs) {
  const labels = Object.fromEntries(trackTabItems(tabs || []).map(item => [item.value, item.label]));
  return SECTIONS.map(section => ({ ...section, label: labels[section.value] || section.label }));
}

// Tracking is a presentation sheet everywhere. Where the sheet's close button sits in the
// system side rail, the sections join it there as grouped rail buttons (like Calendar's
// Filters and Settings) and the form drops its Section row; elsewhere the Section row stays.
export function TrackPresentation({ open, onClose, title, tabs, activeTab, onTabChange, titleColor,
  containerColor, children }) {
  const railItems = useMemo(() => trackRailItems(tabs), [tabs]);
  return <AdaptivePresentationSheet isPresented={open} onDismiss={onClose} onClose={onClose} title={title}
    titleColor={titleColor} containerColor={containerColor}
    railItems={railItems} railValue={activeTab} onRailChange={onTabChange}>
    {({ rail }) => <View style={{ flex: 1, paddingHorizontal: 16 }}>{children({ railTabs: rail })}</View>}
  </AdaptivePresentationSheet>;
}
