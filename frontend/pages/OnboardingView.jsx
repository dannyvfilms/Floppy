import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { OnboardingWizard } from '../onboarding/OnboardingWizard';

export const onboardingLabels = {
  loading: 'Loading setup…',
};

// Resumable onboarding page. The wizard owns step order, progress and actions;
// the adapter supplies the current step body, persisted state and transport.
export function OnboardingView({
  steps = [],
  activeStep,
  completedSteps = [],
  title,
  explanation,
  status = 'in_progress',
  blocked = false,
  blockedTitle,
  blockedMessage,
  notice,
  saveLabel,
  onSaveAndFinish,
  footer = null,
  palette = {},
  buttonPalette = {},
  loading = false,
  labels = {},
  children,
}) {
  const copy = { ...onboardingLabels, ...(labels || {}) };
  if (loading) {
    return <View style={styles.loading}>
      <Text accessibilityLiveRegion="polite" style={[styles.loadingText, { color: palette.textMuted || '#a1a1aa' }]}>{copy.loading}</Text>
    </View>;
  }
  return <View style={styles.page}>
    <OnboardingWizard steps={steps} activeStep={activeStep} completedSteps={completedSteps}
      title={title} explanation={explanation} status={status} blocked={blocked}
      blockedTitle={blockedTitle} blockedMessage={blockedMessage} notice={notice}
      saveLabel={saveLabel} onSaveAndFinish={onSaveAndFinish} palette={palette}
      buttonPalette={buttonPalette}>
      {children}
    </OnboardingWizard>
    {footer}
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16, minWidth: 0 },
  loading: { paddingHorizontal: 4, paddingVertical: 8 },
  loadingText: { fontSize: 13, lineHeight: 19 },
});
