import React from 'react';
import { Image, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { SetupGuide } from '../ui/SetupGuide';
import { TextField } from '../ui/TextField';
import { Icon } from '../ui/Icon';
import { ReorderList } from '../ui/ReorderList';
import { ToggleChip } from '../ui/ToggleChip';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 8,
  focusStyle: {},
};

const defaultButtons = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(239, 68, 68, 0.18)', hovered: 'rgba(239, 68, 68, 0.18)', text: '#f87171', border: 'transparent' },
  radius: 6,
  focusStyle: {},
};

const statusLabels = {
  not_started: 'Not started',
  in_progress: 'In progress',
  completed: 'Completed',
};

const runLabels = {
  queued: 'Queued',
  running: 'Importing…',
  completed: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

function resolveColors(palette) {
  return { ...defaultPalette, ...(palette || {}) };
}

function resolveButtons(palette) {
  return { ...defaultButtons, ...(palette || {}) };
}

function toneChip(colors, tone) {
  if (tone === 'success') {
    return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.16)', badgeText: '#a7f3d0' };
  }
  if (tone === 'warning') {
    return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.16)', badgeText: '#fde68a' };
  }
  if (tone === 'danger') {
    return { ...colors, badgeBorder: colors.danger, badgeBackground: 'rgba(239, 68, 68, 0.16)', badgeText: '#fecaca' };
  }
  if (tone === 'accent') {
    return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.16)', badgeText: '#c7d2fe' };
  }
  return { ...colors, badgeBorder: colors.surfaceMuted, badgeBackground: colors.surfaceStrong, badgeText: colors.textSecondary };
}

function progressChip(colors, state) {
  if (state === 'active') {
    return { ...colors, badgeBorder: colors.accentStrong, badgeBackground: colors.accentStrong, badgeText: colors.accentText };
  }
  if (state === 'completed') {
    return { ...colors, badgeBorder: colors.surfaceMuted, badgeBackground: colors.surfaceStrong, badgeText: colors.textSecondary };
  }
  return { ...colors, badgeBorder: colors.border, badgeBackground: 'transparent', badgeText: colors.textMuted };
}

function runTone(status) {
  if (status === 'completed') return 'success';
  if (status === 'running') return 'accent';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'warning';
  return 'neutral';
}

function SourceIdentity({ source, colors }) {
  const initial = String(source?.name || source?.slug || '?').slice(0, 1).toUpperCase();
  return <View style={styles.sourceIdentity}>
    {source.logo ? <Image source={{ uri: source.logo }} style={{ width: 24, height: 24 }} resizeMode="contain" accessible={false} /> : <View style={[styles.avatar, { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceMuted }]}>
      <Text style={[styles.avatarText, { color: colors.textSecondary }]}>{initial}</Text>
    </View>}
    <View style={styles.sourceCopy}>
      <Text style={[styles.sourceName, { color: colors.text }]}>{source?.name || source?.slug}</Text>
      {source?.description ? <Text style={[styles.sourceDescription, { color: colors.textMuted }]}>{source.description}</Text> : null}
    </View>
  </View>;
}

function CheckRow({ checked, label, description, onPress, colors }) {
  return <Pressable accessibilityRole="checkbox" accessibilityState={{ checked }} onPress={onPress}
    style={({ pressed }) => [
      styles.optionRow,
      {
        borderColor: checked ? colors.accent : colors.border,
        backgroundColor: checked ? 'rgba(99, 102, 241, 0.12)' : colors.surfaceStrong,
      },
      pressed && { opacity: 0.82 },
    ]}>
    <View style={[styles.checkbox, {
      borderColor: checked ? colors.accent : colors.surfaceMuted,
      backgroundColor: checked ? colors.accent : 'transparent',
    }]}>
      {checked ? <Text style={styles.checkboxMark}>✓</Text> : null}
    </View>
    <View style={styles.optionCopy}>
      <Text style={[styles.optionLabel, { color: colors.text }]}>{label}</Text>
      {description ? <Text style={[styles.optionDescription, { color: colors.textMuted }]}>{description}</Text> : null}
    </View>
  </Pressable>;
}

export function OnboardingNotice({ tone = 'info', title, children, palette }) {
  const colors = resolveColors(palette);
  const color = tone === 'error' ? colors.danger : tone === 'success' ? colors.success : colors.accent;
  const background = tone === 'error'
    ? 'rgba(239, 68, 68, 0.12)'
    : tone === 'success'
      ? 'rgba(16, 185, 129, 0.12)'
      : 'rgba(99, 102, 241, 0.12)';
  const fallbackTitle = tone === 'error' ? 'Could not continue' : tone === 'success' ? 'Saved' : 'Setup status';
  return <View accessibilityLiveRegion="polite" style={[styles.notice, { borderColor: color, backgroundColor: background }]}>
    <Text style={[styles.noticeTitle, { color }]}>{title || fallbackTitle}</Text>
    {children ? <Text style={[styles.noticeCopy, { color: colors.textSecondary }]}>{children}</Text> : null}
  </View>;
}

export function OnboardingWizard({
  steps = [],
  activeStep,
  completedSteps = [],
  title,
  explanation,
  children,
  footer,
  status = 'in_progress',
  blocked = false,
  blockedTitle,
  blockedMessage,
  notice,
  saveLabel = 'Save & finish later',
  onSaveAndFinish,
  palette,
  buttonPalette,
  standalone = false,
  heroSource,
  progressArrowIcon,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  const { width } = useWindowDimensions();

  if (blocked) {
    return <SettingsCard title={blockedTitle || 'Guided setup unavailable'} badge="Blocked" palette={toneChip(colors, 'warning')}>
      <Text style={[styles.body, { color: colors.textSecondary }]}>
        {blockedMessage || 'Guided setup is not available for this account.'}
      </Text>
    </SettingsCard>;
  }

  if (standalone) return <View style={{ gap: 24, minWidth: 0 }}>
    <View style={{ gap: 12 }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: 8, rowGap: 12 }}>
        {steps.map((step, index) => <View key={step.slug} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={{ paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6,
            backgroundColor: step.slug === activeStep ? colors.accentStrong : completedSteps.includes(step.slug) ? colors.surfaceStrong : 'transparent' }}>
            <Text style={{ color: step.slug === activeStep ? colors.accentText : colors.textMuted, fontSize: 12, lineHeight: 16 }}>{step.label}</Text>
          </View>
          {index < steps.length - 1 && progressArrowIcon ? <Icon spec={progressArrowIcon} color={colors.textMuted} size={10} /> : null}
        </View>)}
      </View>
      {onSaveAndFinish && status !== 'completed' ? <Pressable accessibilityRole="link" onPress={onSaveAndFinish} style={{ alignSelf: 'flex-start' }}>
        <Text style={{ color: colors.textMuted, fontSize: 12, lineHeight: 16, textDecorationLine: 'underline' }}>{saveLabel}</Text>
      </Pressable> : null}
    </View>
    {notice ? <OnboardingNotice tone={notice.tone} title={notice.title} palette={colors}>{notice.text}</OnboardingNotice> : null}
    <View style={{ backgroundColor: colors.surface, borderRadius: colors.radius, padding: width >= 768 ? 32 : 24,
      flexDirection: width >= 768 ? 'row' : 'column', gap: width >= 768 ? 32 : 24 }}>
      <View style={{ width: width >= 768 ? '33.333%' : '100%', gap: 16 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          {heroSource ? <Image source={heroSource} style={{ width: 52, height: 42, borderRadius: 8 }} resizeMode="contain" accessible={false} /> : null}
          <Text role="heading" aria-level={1} style={{ color: colors.text, fontSize: 18, lineHeight: 28, fontWeight: '700', flexShrink: 1 }}>{title}</Text>
        </View>
        {typeof explanation === 'string' ? <View style={{ gap: 12 }}>{explanation.split('\n\n').map((paragraph, index) =>
          <Text key={index} style={{ color: colors.textMuted, fontSize: 14, lineHeight: 20 }}>{paragraph}</Text>)}</View> : explanation}
      </View>
      <View style={{ flex: width >= 768 ? 1 : undefined, minWidth: 0,
        borderLeftWidth: width >= 768 ? 1 : 0, borderLeftColor: colors.border, paddingLeft: width >= 768 ? 32 : 0 }}>
        {children}
        {footer || null}
      </View>
    </View>
  </View>;

  return <View style={styles.stack}>
    <View style={styles.progressHeader}>
      <View style={styles.progressChips}>
        {steps.map((step, index) => {
          const state = step.slug === activeStep ? 'active' : completedSteps.includes(step.slug) ? 'completed' : 'upcoming';
          return <View key={step.slug} style={styles.progressItem}>
            <Chip label={step.label} palette={progressChip(colors, state)} />
            {index < steps.length - 1 ? <Text style={[styles.progressArrow, { color: colors.textMuted }]}>›</Text> : null}
          </View>;
        })}
      </View>
      {onSaveAndFinish && status !== 'completed'
        ? <Button label={saveLabel} tone="surface" onPress={onSaveAndFinish} palette={buttons} />
        : null}
    </View>
    {notice ? <OnboardingNotice tone={notice.tone} title={notice.title} palette={colors}>{notice.text}</OnboardingNotice> : null}
    <SettingsCard title={title} badge={status === 'in_progress' ? undefined : statusLabels[status]} palette={colors}>
      {explanation ? <View style={styles.explanation}>
        {typeof explanation === 'string'
          ? <Text style={[styles.body, { color: colors.textMuted }]}>{explanation}</Text>
          : explanation}
      </View> : null}
      {children}
      {footer ? <View style={[styles.footer, { borderColor: colors.border }]}>{footer}</View> : null}
    </SettingsCard>
  </View>;
}

export function OnboardingMediaTypesStep({
  options = [],
  selected = [],
  onToggle,
  onContinue,
  onSkip,
  error,
  busy = false,
  palette,
  buttonPalette,
  dragIcon,
  onMove,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  return <View style={styles.section}>
    {dragIcon ? <ReorderList items={options} keyForItem={option => option.value} labelForItem={option => option.label}
      onMove={onMove} icon={dragIcon} palette={colors} disabled={busy} gap={12}
      renderItem={(option, index, handle) => <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        minHeight: 44, padding: 12, gap: 8, borderRadius: 6, backgroundColor: colors.surfaceStrong }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 }}>
          {handle}
          {option.icon ? <Icon spec={option.icon} color={colors.textMuted} size={20} /> : null}
          <Text style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 20, flexShrink: 1 }}>{option.label}</Text>
        </View>
        <ToggleChip label={option.label} labelHidden value={selected.includes(option.value)} onChange={() => onToggle?.(option.value)}
          disabled={busy} palette={{ ...colors, pageCards: true }} />
      </View>} /> : <View style={styles.optionList}>
      {options.map(option => <CheckRow key={option.value} checked={selected.includes(option.value)}
        label={option.label} onPress={() => onToggle?.(option.value)} colors={colors} />)}
    </View>}
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    <View style={styles.actions}>
      <Button label="I'll choose later" tone="surface" disabled={busy} onPress={onSkip} palette={buttons} />
      <Button label="Continue" busy={busy} onPress={onContinue} palette={buttons} />
    </View>
  </View>;
}

export function OnboardingMetadataStep({
  suggestions = [],
  values = {},
  onChange,
  onSkip,
  onContinue,
  onOpenDocs,
  busy = false,
  error,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  const nested = { ...colors, background: colors.surfaceStrong, border: colors.surfaceMuted };
  return <View style={styles.section}>
    {suggestions.length ? suggestions.map(suggestion => <SettingsCard key={suggestion.slug}
      title={suggestion.label} badge={suggestion.badge} palette={nested}>
      <Text style={[styles.body, { color: colors.textSecondary }]}>{suggestion.why}</Text>
      <Pressable accessibilityRole="link" accessibilityLabel={`Get a ${suggestion.label} key`}
        onPress={() => onOpenDocs?.(suggestion)} style={styles.textLink}>
        <Text style={[styles.linkText, { color: colors.accent }]}>Get a key</Text>
      </Pressable>
      <View style={styles.fields}>
        {(suggestion.fields || []).map(field => {
          const key = `${suggestion.slug}-${field.name}`;
          return <TextField key={key} id={key} name={field.name} label={field.label}
            type={field.secret ? 'password' : 'text'} value={values[key] || ''}
            onChangeText={text => onChange?.(key, text)} palette={colors} />;
        })}
      </View>
    </SettingsCard>) : <Text style={[styles.body, { color: colors.textMuted }]}>Nothing to add for the media types you picked.</Text>}
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    <View style={styles.actions}>
      <Button label="Skip for now" tone="surface" disabled={busy} onPress={onSkip} palette={buttons} />
      <Button label="Continue" busy={busy} onPress={onContinue} palette={buttons} />
    </View>
  </View>;
}

export function OnboardingServicesStep({
  mediaTypeLabel,
  stepNumber,
  stepTotal,
  candidates = [],
  selected = [],
  onToggle,
  onNext,
  isLast = false,
  busy = false,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  return <View style={styles.section}>
    <Text style={[styles.meta, { color: colors.textMuted }]}>
      {`Step ${stepNumber} of ${stepTotal} · ${mediaTypeLabel}`}
    </Text>
    <View style={styles.optionList}>
      {candidates.length ? candidates.map(source => <CheckRow key={source.slug}
        checked={selected.includes(source.slug)} label={source.name}
        description={source.description} onPress={() => onToggle?.(source.slug)} colors={colors} />)
        : <Text style={[styles.body, { color: colors.textMuted }]}>
          {`No dedicated services yet for ${String(mediaTypeLabel).toLowerCase()}. You can always bring in existing data with a backup or CSV import later.`}
        </Text>}
    </View>
    <Text style={[styles.hint, { color: colors.textMuted }]}>Shared services stay selected across media types.</Text>
    <View style={styles.actions}>
      <View />
      <Button label={isLast ? 'Continue' : 'Next'} busy={busy} onPress={onNext} palette={buttons} />
    </View>
  </View>;
}

export function OnboardingSummaryStep({
  mediaTypeCount = 0,
  selectedSources = [],
  connectedSources = [],
  onLater,
  onSetupNow,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  return <View style={styles.section}>
    {selectedSources.length ? <View style={styles.optionList}>
      {selectedSources.map(source => <View key={source.slug} style={[styles.sourceRow, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
        <SourceIdentity source={source} colors={colors} />
        <Chip label={connectedSources.includes(source.slug) ? 'Connected' : 'Selected'}
          palette={toneChip(colors, connectedSources.includes(source.slug) ? 'success' : 'neutral')} />
      </View>)}
    </View> : <Text style={[styles.body, { color: colors.textMuted }]}>
      You didn't pick any services to connect, that's fine, you can add them anytime from Settings &gt; Import.
    </Text>}
    <View style={styles.actions}>
      <Button label="Set up later" tone="surface" onPress={onLater} palette={buttons} />
      <Button label="Set up now" disabled={!selectedSources.length} onPress={onSetupNow} palette={buttons} />
    </View>
  </View>;
}

export function OnboardingServiceSetupStep({
  source,
  remainingCount = 0,
  showRemainingCount = true,
  values = {},
  onChange,
  onConnect,
  onSkip,
  busy = false,
  error,
  traktConfigured = true,
  traktProfile = 'public',
  onTraktProfileChange,
  uploadName,
  device = {},
  onStartDevice,
  onCheckDevice,
  onOpenImport,
  oauthContent,
  deviceContent,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  if (!source) return null;
  const variant = !source.inlineSupported ? 'device'
    : source.slug === 'trakt' ? 'trakt'
      : source.isOauth ? 'oauth'
        : source.uploadFieldName ? 'upload'
          : 'form';
  const fieldPalette = colors;
  const traktOptions = [
    { value: 'public', label: 'Public profile', disabled: !traktConfigured },
    { value: 'private', label: 'Private profile (OAuth)', disabled: !traktConfigured },
    { value: 'csv', label: 'Data export file' },
  ];

  return <View style={styles.section}>
    {showRemainingCount ? <Text style={[styles.meta, { color: colors.textMuted }]}>
      {`${remainingCount} ${remainingCount === 1 ? 'service' : 'services'} left to connect.`}
    </Text> : null}
    <View style={[styles.setupPanel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <SourceIdentity source={source} colors={colors} />
      <Text style={[styles.body, { color: colors.textMuted }]}>{source.setupCopy}</Text>
      {variant === 'form' ? <View style={styles.fields}>
        {(source.connectFields || []).map(field => <TextField key={field.name} id={`${source.slug}-${field.name}`}
          label={field.label} name={field.name} type={field.type === 'password' ? 'password' : 'text'}
          value={values[field.name] || ''} onChangeText={text => onChange?.(field.name, text)}
          palette={fieldPalette} />)}
        <Button label="Connect" busy={busy} onPress={onConnect} palette={buttons} />
      </View> : null}
      {variant === 'oauth' ? oauthContent || <View style={styles.fields}>
        <Button label={`Connect ${source.name}`} busy={busy} width="full" onPress={onConnect} palette={buttons} />
        <Text style={[styles.hint, { color: colors.textMuted }]}>
          {`You will be sent to ${source.name} to sign in, then brought right back here.`}
        </Text>
      </View> : null}
      {variant === 'upload' ? <View style={styles.fields}>
        <Button label={uploadName ? `Selected ${uploadName}` : 'Select File'} busy={busy} onPress={onConnect} palette={buttons} />
        <Text style={[styles.hint, { color: colors.textMuted }]}>{`Accepted file: ${source.uploadAccept || '.csv'}`}</Text>
      </View> : null}
      {variant === 'trakt' ? <View style={styles.fields}>
        <SelectField id="trakt-profile" label="Profile" options={traktOptions} value={traktProfile}
          onChange={event => onTraktProfileChange?.(event.target.value)} palette={fieldPalette} />
        {!traktConfigured ? <Text style={[styles.hint, { color: colors.warning }]}>
          Profile imports need TRAKT_API configured (VIP-only). Use a data export instead.
        </Text> : null}
        {traktProfile === 'public' ? <View style={styles.fields}>
          <TextField id="trakt-public-user" label="Public Trakt username" name="user"
            value={values.user || ''} onChangeText={text => onChange?.('user', text)} palette={fieldPalette} />
          <Button label="Import" busy={busy} onPress={onConnect} palette={buttons} />
        </View> : null}
        {traktProfile === 'private' ? oauthContent || <Button label="Connect with Trakt" busy={busy} width="full"
          onPress={onConnect} palette={buttons} /> : null}
        {traktProfile === 'csv' ? <View style={styles.fields}>
          <Button label={uploadName ? `Selected ${uploadName}` : 'Select Export File'} busy={busy}
            onPress={onConnect} palette={buttons} />
          <Text style={[styles.hint, { color: colors.textMuted }]}>Accepted files: .zip, .json, .csv</Text>
        </View> : null}
      </View> : null}
      {variant === 'device' ? deviceContent || <View style={styles.fields}>
        {!device.started ? <View style={styles.fields}>
          <TextField id="device-server-url" label="Server URL" name="server_url"
            type="url" value={values.server_url || ''} onChangeText={text => onChange?.('server_url', text)}
            palette={fieldPalette} />
          <Button label="Start device login" busy={busy} onPress={onStartDevice} palette={buttons} />
          <Text style={[styles.hint, { color: colors.textMuted }]}>
            This service uses a device-code login rather than a one-step form.
          </Text>
        </View> : <View style={styles.devicePanel}>
          <Text style={[styles.body, { color: colors.textSecondary }]}>Enter this code on your server:</Text>
          <Text style={[styles.deviceCode, { color: colors.text, borderColor: colors.border }]}>{device.code}</Text>
          <Text selectable style={[styles.hint, { color: colors.textMuted }]}>{device.verificationUri}</Text>
          <Text style={[styles.body, { color: colors.warning }]}>{device.status || 'Waiting for approval…'}</Text>
          <View style={styles.actions}>
            <Button label="Check again" busy={busy} onPress={onCheckDevice} palette={buttons} />
            <Button label="Open Import setup instead" tone="surface" onPress={onOpenImport} palette={buttons} />
          </View>
        </View>}
      </View> : null}
    </View>
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    <View style={styles.actions}>
      <Button label="Skip for now" tone="surface" disabled={busy} onPress={onSkip} palette={buttons} />
      <View />
    </View>
  </View>;
}

export function OnboardingIntegrationStep({
  source,
  guide,
  copy = {},
  onCopy,
  onOpenLink,
  onSkip,
  onContinue,
  busy = false,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  return <View style={styles.section}>
    <View style={[styles.setupPanel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <SourceIdentity source={source} colors={colors} />
      <Text style={[styles.body, { color: colors.textSecondary }]}>
        {`You imported ${source?.name || 'this service'}'s history, but that only covers what already happened. Set up a webhook so new plays are tracked as they happen.`}
      </Text>
      {guide ? <SetupGuide guide={guide} copy={copy} onCopy={onCopy} onOpenLink={onOpenLink}
        palette={colors} buttonPalette={buttons} /> : null}
    </View>
    <View style={styles.actions}>
      <Button label="Skip for now" tone="surface" disabled={busy} onPress={onSkip} palette={buttons} />
      <Button label="I’ve added the webhook" busy={busy} onPress={onContinue} palette={buttons} />
    </View>
  </View>;
}

export function OnboardingImportStatusStep({
  sources = [],
  onContinue,
  onRefresh,
  refreshing = false,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  return <View style={styles.section}>
    <Text style={[styles.body, { color: colors.textSecondary }]}>
      Your connected services are queued to import. This can take a few minutes depending on how much history they have.
    </Text>
    {sources.length ? <View style={styles.optionList}>
      {sources.map(item => <View key={item.source.slug} style={[styles.sourceRow, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
        <SourceIdentity source={item.source} colors={colors} />
        <Chip label={runLabels[item.run?.status] || 'Queued'} palette={toneChip(colors, runTone(item.run?.status))} />
        {item.run?.error ? <Text style={[styles.error, { color: colors.danger }]}>{item.run.error}</Text> : null}
      </View>)}
    </View> : <Text style={[styles.body, { color: colors.textMuted }]}>
      No services connected yet. You can connect one anytime from Settings &gt; Import.
    </Text>}
    <View style={styles.actions}>
      <Button label="Refresh progress" tone="surface" busy={refreshing} onPress={onRefresh} palette={buttons} />
      <Button label="Continue" onPress={onContinue} palette={buttons} />
    </View>
  </View>;
}

export function OnboardingCompleteStep({
  mediaTypeCount = 0,
  connectedSources = [],
  onRestart,
  palette,
  buttonPalette,
}) {
  const colors = resolveColors(palette);
  const buttons = resolveButtons(buttonPalette);
  return <View style={styles.section}>
    <Text style={[styles.body, { color: colors.textSecondary }]}>
      Your setup is saved. You can change media types, services and metadata keys anytime in Settings.
    </Text>
    <View style={[styles.summaryPanel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.summaryLine, { color: colors.text }]}>
        {`${mediaTypeCount} media ${mediaTypeCount === 1 ? 'type' : 'types'} tracked`}
      </Text>
      <Text style={[styles.summaryLine, { color: colors.text }]}>
        {`${connectedSources.length} ${connectedSources.length === 1 ? 'service' : 'services'} connected`}
      </Text>
    </View>
    {connectedSources.length ? <View style={styles.optionList}>
      {connectedSources.map(source => <View key={source.slug} style={[styles.sourceRow, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
        <SourceIdentity source={source} colors={colors} />
        <Chip label="Connected" palette={toneChip(colors, 'success')} />
      </View>)}
    </View> : null}
    <View style={styles.actions}>
      <Button label="Run guided setup again" tone="surface" onPress={onRestart} palette={buttons} />
      <View />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 12, minWidth: 0 },
  progressHeader: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  progressChips: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 4, flexShrink: 1 },
  progressItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  progressArrow: { fontSize: 12 },
  notice: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 2 },
  noticeTitle: { fontSize: 13, fontWeight: '700' },
  noticeCopy: { fontSize: 12, lineHeight: 17 },
  explanation: { gap: 6 },
  body: { fontSize: 13, lineHeight: 19 },
  meta: { fontSize: 12 },
  hint: { fontSize: 12, lineHeight: 17 },
  error: { fontSize: 12, lineHeight: 17 },
  section: { gap: 12, minWidth: 0 },
  optionList: { gap: 8 },
  optionRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, borderWidth: 1, borderRadius: 8, padding: 10 },
  optionCopy: { flexShrink: 1, gap: 2 },
  optionLabel: { fontSize: 14, fontWeight: '500' },
  optionDescription: { fontSize: 12, lineHeight: 17 },
  checkbox: { alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: 4, borderWidth: 1, marginTop: 1 },
  checkboxMark: { color: '#ffffff', fontSize: 11, fontWeight: '700', lineHeight: 14 },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 },
  footer: { borderTopWidth: 1, paddingTop: 12 },
  fields: { gap: 8, minWidth: 0 },
  textLink: { alignSelf: 'flex-start', paddingVertical: 2 },
  linkText: { fontSize: 12, fontWeight: '600', textDecorationLine: 'underline' },
  sourceRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderWidth: 1, borderRadius: 8, padding: 10 },
  sourceIdentity: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1, minWidth: 0 },
  avatar: { alignItems: 'center', justifyContent: 'center', width: 26, height: 26, borderRadius: 13, borderWidth: 1 },
  avatarText: { fontSize: 12, fontWeight: '700' },
  sourceCopy: { flexShrink: 1, gap: 1, minWidth: 0 },
  sourceName: { fontSize: 14, fontWeight: '600' },
  sourceDescription: { fontSize: 12, lineHeight: 17 },
  setupPanel: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  devicePanel: { gap: 8, alignItems: 'flex-start' },
  deviceCode: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6, fontSize: 18, fontWeight: '700', letterSpacing: 2 },
  summaryPanel: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 4 },
  summaryLine: { fontSize: 14, fontWeight: '600' },
});
