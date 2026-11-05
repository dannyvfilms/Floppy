import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { SettingsCard } from './SettingsCard';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 6,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
  focusStyle: {},
};

function badgesFor(colors) {
  return {
    outline: { color: colors.textSecondary, borderColor: colors.surfaceMuted, borderWidth: 1 },
    indigo: { color: '#ffffff', backgroundColor: colors.accentStrong },
  };
}

function LinkRow({ label, description, url, onOpenUrl, palette, badge }) {
  const open = onOpenUrl ? () => onOpenUrl(url) : undefined;
  return <Pressable accessibilityRole="link" accessibilityLabel={label}
    accessibilityHint={url} accessibilityState={{ disabled: !onOpenUrl }}
    disabled={!onOpenUrl} onPress={open}
    style={({ pressed }) => [styles.linkRow, {
      backgroundColor: palette.surfaceStrong, borderColor: palette.border,
    }, pressed && onOpenUrl && { opacity: 0.75 }]}>
    <View style={styles.linkBody}>
      <View style={styles.linkHeading}>
        <Text style={[styles.linkLabel, { color: palette.accent }]}>{label}</Text>
        {badge ? <Badge label={badge} size="xs" tone="outline" palette={badgesFor(palette)} /> : null}
      </View>
      {description ? <Text style={[styles.linkCopy, { color: palette.textMuted }]}>{description}</Text> : null}
      <Text style={[styles.linkUrl, { color: palette.textMuted }]} numberOfLines={1}>{url}</Text>
    </View>
    <Text style={[styles.linkAction, { color: palette.textSecondary }]}>Open</Text>
  </Pressable>;
}

function LinkListCard({ title, description, items = [], onOpenUrl, palette }) {
  return <SettingsCard title={title} palette={palette}>
    {description ? <Text style={[styles.copy, { color: palette.textMuted }]}>{description}</Text> : null}
    <View style={styles.column}>
      {items.map(item => <LinkRow key={item.label} label={item.label} description={item.description}
        url={item.url} badge={item.badge} onOpenUrl={onOpenUrl} palette={palette} />)}
    </View>
  </SettingsCard>;
}

export function ReleaseUpdateBanner({
  releaseTag,
  onDismiss,
  onViewWhatsNew,
  palette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  if (!releaseTag) return null;
  return <View accessibilityLiveRegion="polite" style={[styles.banner, {
    backgroundColor: colors.surfaceStrong, borderColor: colors.accent,
  }]}>
    <Text style={[styles.bannerText, { color: colors.textSecondary }]}>Floppy was updated to {releaseTag}.</Text>
    <Pressable accessibilityRole="link" accessibilityLabel="See what's new"
      onPress={onViewWhatsNew} style={({ pressed }) => [styles.bannerLink, pressed && { opacity: 0.7 }]}>
      <Text style={[styles.bannerLinkText, { color: colors.accent }]}>See what's new</Text>
    </Pressable>
    <Pressable accessibilityRole="button" accessibilityLabel="Dismiss update notice"
      onPress={onDismiss} style={({ pressed }) => [styles.dismiss, pressed && { opacity: 0.7 }]}>
      <Text style={[styles.dismissText, { color: colors.textMuted }]}>×</Text>
    </Pressable>
  </View>;
}

export function AboutOverviewCard({
  description = 'Floppy is an open-source, self-hosted media tracker and personal diary. Track, rate, and organize movies, shows, video games, books, music, podcasts, anime, comics, and more in one unified library.',
  sponsorUrl = 'https://github.com/sponsors/dannyvfilms?metadata_source=app-about-description',
  onOpenUrl,
  palette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  return <SettingsCard title="About Floppy" palette={colors}>
    <Text style={[styles.copy, { color: colors.textSecondary }]}>{description}</Text>
    <Text style={[styles.copy, { color: colors.textMuted }]}>Floppy is free and supported by <Text
      accessibilityRole="link" onPress={() => onOpenUrl?.(sponsorUrl)}
      style={[styles.inlineLink, { color: colors.accent }]}>users like you</Text>.</Text>
  </SettingsCard>;
}

export function WhatsNewCard({ releases = [], releasesUrl, onOpenUrl, palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const [openTag, setOpenTag] = useState(releases[0]?.tag || '');
  return <SettingsCard title="What's new" palette={colors}>
    {releases.length ? releases.map(release => {
      const open = openTag === release.tag;
      return <View key={release.tag} style={[styles.release, {
        backgroundColor: colors.surfaceStrong, borderColor: colors.border,
      }]}>
        <Pressable accessibilityRole="button" accessibilityLabel={`${release.tag} release notes`}
          accessibilityState={{ expanded: open }}
          onPress={() => setOpenTag(open ? '' : release.tag)}
          style={({ pressed }) => [styles.releaseHeading, pressed && { opacity: 0.75 }]}>
          <Text style={[styles.releaseChevron, { color: colors.textMuted }]}>{open ? '▾' : '▸'}</Text>
          <Text style={[styles.releaseTag, { color: colors.text }]}>{release.tag}</Text>
          {release.published ? <Text style={[styles.releaseDate, { color: colors.textMuted }]}>{release.published}</Text> : null}
          {release.installed ? <Badge label="Installed" size="sm" tone="indigo" palette={badgesFor(colors)} /> : null}
          {release.newer ? <Badge label="Newer than yours" size="sm" tone="outline" palette={badgesFor(colors)} /> : null}
        </Pressable>
        {open ? <View style={styles.releaseBody}>
          {release.highlights?.length ? release.highlights.map((item, index) => <Text key={index}
            style={[styles.bullet, { color: colors.textSecondary }]}>• {item.title ? `${item.title} — ` : ''}{item.text}</Text>)
            : <Text style={[styles.copy, { color: colors.textMuted }]}>See the release page for what changed.</Text>}
          <Pressable accessibilityRole="link" accessibilityLabel={`${release.tag} release page on GitHub`}
            onPress={() => onOpenUrl?.(release.url)}
            style={({ pressed }) => [styles.inlineAction, pressed && { opacity: 0.7 }]}>
            <Text style={[styles.linkLabel, { color: colors.accent }]}>Release page on GitHub</Text>
          </Pressable>
        </View> : null}
      </View>;
    }) : <Text style={[styles.copy, { color: colors.textMuted }]}>Release notes could not be loaded from GitHub.</Text>}
    <Pressable accessibilityRole="link" accessibilityLabel="All releases on GitHub"
      onPress={() => onOpenUrl?.(releasesUrl)}
      style={({ pressed }) => [styles.inlineAction, pressed && { opacity: 0.7 }]}>
      <Text style={[styles.linkLabel, { color: colors.accent }]}>All releases on GitHub</Text>
    </Pressable>
  </SettingsCard>;
}

function InstallSteps({ title, steps, palette }) {
  return <View style={[styles.stepCard, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
    <Text style={[styles.stepTitle, { color: palette.text }]}>{title}</Text>
    {steps.map((step, index) => <Text key={step} style={[styles.bullet, { color: palette.textMuted }]}>{index + 1}. {step}</Text>)}
  </View>;
}

export function InstallCard({
  installAvailable = false,
  installBusy = false,
  installStatus,
  guideUrl = 'https://github.com/dannyvfilms/Floppy/wiki/2.-User-Guide#installing-floppy-on-your-phone',
  onInstall,
  onOpenUrl,
  palette = {},
  buttonPalette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  return <SettingsCard title="Install Floppy" palette={colors}>
    <Text style={[styles.copy, { color: colors.textSecondary }]}>Floppy is an installable PWA. Add it to your Home Screen to launch it like an app directly from your browser.</Text>
    {installAvailable ? <Button label="Install Floppy" busy={installBusy}
      onPress={onInstall} palette={buttons} /> : null}
    {installStatus ? <Text accessibilityLiveRegion="polite" style={[styles.copy, { color: colors.textMuted }]}>{installStatus}</Text> : null}
    <View style={styles.column}>
      <InstallSteps title="iOS and iPadOS" palette={colors} steps={[
        'Open this instance in Safari.',
        'Tap the Share button.',
        'Choose Add to Home Screen.',
        'Turn on Open as Web App if it is shown, then tap Add.',
      ]} />
      <InstallSteps title="Android" palette={colors} steps={[
        'Open this instance in Chrome.',
        'Open the browser menu.',
        'Choose Add to Home screen.',
        "Confirm with Install, following your browser's wording.",
      ]} />
    </View>
    <Text style={[styles.copy, { color: colors.textMuted }]}>Installing on a phone instead? The <Text
      accessibilityRole="link" onPress={() => onOpenUrl?.(guideUrl)}
      style={[styles.inlineLink, { color: colors.accent }]}>installation guide</Text> has the iOS and Android steps.</Text>
    <Text style={[styles.copy, { color: colors.textMuted }]}>No install control anywhere? Serve the instance over HTTPS and open it in a full browser rather than an in-app one. Tracking still needs a connection to your Floppy server.</Text>
    <Pressable accessibilityRole="link" accessibilityLabel="Installation guide"
      onPress={() => onOpenUrl?.(guideUrl)}
      style={({ pressed }) => [styles.inlineAction, pressed && { opacity: 0.7 }]}>
      <Text style={[styles.linkLabel, { color: colors.accent }]}>Installation guide</Text>
    </Pressable>
  </SettingsCard>;
}

export function ProjectResourcesCard({ resources = [], onOpenUrl, palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  return <LinkListCard title="Project Resources" items={resources}
    onOpenUrl={onOpenUrl} palette={colors} />;
}

export function DeveloperSpecsCard({ specs = [], onOpenUrl, palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const items = specs.map(spec => ({
    label: spec.label,
    description: `${spec.format} · ${spec.description}`,
    url: spec.url,
  }));
  return <LinkListCard title="Developer & API Specifications"
    description="Reviewed contracts and live schemas served by this instance."
    items={items} onOpenUrl={onOpenUrl} palette={colors} />;
}

export function AttributionsCard({ attributions = [], onOpenUrl, palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const items = attributions.map(item => ({
    label: item.provider,
    description: item.media,
    url: item.url,
  }));
  return <LinkListCard title="Metadata & Attributions" items={items}
    onOpenUrl={onOpenUrl} palette={colors} />;
}

export function LicenseCard({ licenses = [], onOpenUrl, palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const items = licenses.map(item => ({
    label: item.subject,
    description: item.terms,
    url: item.url,
  }));
  return <LinkListCard title="License & Legal" items={items}
    onOpenUrl={onOpenUrl} palette={colors} />;
}

export function AboutVersionFooter({ version, commit, palette = {} }) {
  const colors = { ...defaultPalette, ...palette };
  return <View style={[styles.version, { borderColor: colors.border }]}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>Version: <Text style={styles.mono}>{version || 'Unavailable'}</Text>{commit ? <> <Text style={{ color: colors.textMuted }}>|</Text> Commit: <Text style={styles.mono}>{commit}</Text></> : null}</Text>
  </View>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 13, lineHeight: 19 },
  column: { gap: 8 },
  banner: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10 },
  bannerText: { flexGrow: 1, flexShrink: 1, fontSize: 13 },
  bannerLink: { paddingVertical: 2 },
  bannerLinkText: { fontSize: 13, fontWeight: '600', textDecorationLine: 'underline' },
  dismiss: { paddingHorizontal: 4 },
  dismissText: { fontSize: 18, fontWeight: '600' },
  inlineLink: { textDecorationLine: 'underline' },
  inlineAction: { alignSelf: 'flex-start', paddingVertical: 2 },
  linkRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, borderWidth: 1, borderRadius: 8, padding: 12 },
  linkBody: { flexShrink: 1, gap: 2 },
  linkHeading: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  linkLabel: { fontSize: 13, fontWeight: '600', textDecorationLine: 'underline' },
  linkCopy: { fontSize: 12, lineHeight: 17 },
  linkUrl: { fontSize: 11, lineHeight: 15 },
  linkAction: { fontSize: 12, fontWeight: '600' },
  release: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 8 },
  releaseHeading: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  releaseChevron: { fontSize: 13 },
  releaseTag: { fontSize: 13, fontWeight: '600', fontFamily: 'Courier' },
  releaseDate: { fontSize: 12 },
  releaseBody: { gap: 6 },
  bullet: { fontSize: 12, lineHeight: 18 },
  stepCard: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 4 },
  stepTitle: { fontSize: 13, fontWeight: '600' },
  version: { borderTopWidth: 1, paddingTop: 10 },
  mono: { fontFamily: 'Courier' },
});
