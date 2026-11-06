import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';

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
  link: '#818cf8',
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

const defaultLabels = {
  banner: {
    updated: 'Floppy was updated to {tag}.',
    whatsNew: "See what's new",
    dismiss: 'Dismiss update notice',
  },
  overview: {
    title: 'About Floppy',
    description: 'Floppy is an open-source, self-hosted media tracker and personal diary. Track, rate, and organize movies, shows, video games, books, music, podcasts, anime, comics, and more in one unified library.',
    support: 'Floppy is free and supported by',
    supportLink: 'users like you',
  },
  whatsNew: {
    title: "What's new",
    empty: 'Release notes could not be loaded from GitHub.',
    loading: 'Loading release notes…',
    noHighlights: 'See the release page for what changed.',
    releasePage: 'Release page on GitHub',
    allReleases: 'All releases on GitHub',
    installed: 'Installed',
    newer: 'Newer than yours',
    releaseNotes: '{tag} release notes',
    releasePageLabel: '{tag} release page on GitHub',
  },
  install: {
    title: 'Install Floppy',
    intro: 'Floppy is an installable PWA. Add it to your Home Screen to launch it like an app directly from your browser.',
    install: 'Install Floppy',
    iosTitle: 'iOS and iPadOS',
    iosSteps: [
      'Open this instance in Safari.',
      'Tap the Share button.',
      'Choose Add to Home Screen.',
      'Turn on Open as Web App if it is shown, then tap Add.',
    ],
    androidTitle: 'Android',
    androidSteps: [
      'Open this instance in Chrome.',
      'Open the browser menu.',
      'Choose Add to Home screen.',
      "Confirm with Install, following your browser's wording.",
    ],
    guidePrefix: 'Installing on a phone instead? The',
    guideLink: 'installation guide',
    guideSuffix: 'has the iOS and Android steps.',
    noControl: 'No install control anywhere? Serve the instance over HTTPS and open it in a full browser rather than an in-app one. Tracking still needs a connection to your Floppy server.',
    guideLabel: 'Installation guide',
    installedStatus: 'Installing Floppy. Look for it alongside your other apps.',
    dismissedStatus: 'Installation dismissed. You can still add Floppy using the steps below.',
    failedStatus: 'Your browser could not open the install prompt. Use the steps below instead.',
    unavailableStatus: 'The install prompt is not available right now. Use the steps below instead.',
    installedBadge: 'Installed',
    webBadge: 'Web install',
  },
  links: { open: 'Open' },
  resources: {
    title: 'Project Resources',
    columns: ['Resource', 'Purpose', 'Destination'],
  },
  specs: {
    title: 'Developer & API Specifications',
    columns: ['Specification', 'Format / Standard', 'Actions'],
    open: 'Open',
    openDocs: 'Open Docs',
    preview: 'Preview',
    download: 'Download',
    previewLabel: 'Preview {label}',
    downloadLabel: 'Download {label}',
  },
  attributions: {
    title: 'Metadata & Attributions',
    columns: ['Provider / Service', 'Supported Media', 'Attribution Link'],
    open: 'Open',
  },
  licenses: {
    title: 'License & Legal',
    columns: ['Subject', 'License / Terms', 'Details'],
    open: 'Open',
  },
  version: {
    version: 'Version:',
    commit: 'Commit:',
    unavailable: 'Unavailable',
  },
};

function format(template, values) {
  return String(template || '').replace(/\{(\w+)\}/g, (match, key) =>
    values[key] === undefined ? match : String(values[key]));
}

function mergeLabels(defaults, labels) {
  return { ...defaults, ...(labels || {}) };
}

function useColors(palette) {
  return { ...defaultPalette, ...palette, link: palette?.link || palette?.accent || defaultPalette.link };
}

function SectionHeading({ icon, title, colors, level = 3 }) {
  return <View style={styles.heading}>
    {icon ? <View style={[styles.headingIcon, { fontSize: 20, color: colors.link }]}>
      <Icon spec={icon} />
    </View> : null}
    <Text role="heading" aria-level={level}
      style={[styles.headingText, { color: colors.textSecondary }]}>{title}</Text>
  </View>;
}

function Section({ icon, title, colors, children, bodyStyle, nativeID, testID }) {
  return <View style={styles.section} nativeID={nativeID} testID={testID}>
    <SectionHeading icon={icon} title={title} colors={colors} />
    <View style={[styles.sectionBody, bodyStyle]}>{children}</View>
  </View>;
}

function InlineLink({ label, onPress, accessibilityLabel, colors, style }) {
  return <Text accessibilityRole="link" accessibilityLabel={accessibilityLabel || label}
    onPress={onPress} style={[styles.inlineLink, { color: colors.link }, style]}>{label}</Text>;
}

function TableCell({ children, width, style, colors, right = false }) {
  return <View role="cell" style={[styles.cell, width != null && { width },
    right && styles.cellRight, style]}>
    {children}
  </View>;
}

function DataTable({ columns, rows, widths, mobileWidths, mobileWidth, colors, testID }) {
  const { width } = useWindowDimensions();
  const narrow = width < 768;
  const header = <View role="row" style={[styles.tableHead, {
    backgroundColor: colors.surfaceStrong, borderColor: colors.border,
  }]}>
    {columns.map((column, index) => <View role="columnheader" key={`${column}-${index}`}
      style={[styles.headCell, narrow ? { width: mobileWidths[index] } : { flexBasis: `${widths[index] * 100}%` },
        index === columns.length - 1 && styles.cellRight]}>
      <Text style={[styles.headText, { color: colors.textMuted }]}>{column}</Text>
    </View>)}
  </View>;

  const body = rows.map((row, rowIndex) => <View role="row" key={row.key || rowIndex}
    style={[styles.tableRow, { backgroundColor: colors.surface, borderColor: colors.border },
      rowIndex > 0 && { borderTopWidth: 1 }]}>
    {row.cells.map((cell, cellIndex) => <TableCell key={cellIndex}
      width={narrow ? mobileWidths[cellIndex] : undefined}
      style={!narrow ? { flexBasis: `${widths[cellIndex] * 100}%` } : undefined}
      right={cellIndex === row.cells.length - 1} colors={colors}>
      {cell}
    </TableCell>)}
  </View>);

  const table = <View role="table" testID={testID} style={[styles.table, {
    borderColor: colors.border, borderRadius: colors.radius,
  }, narrow && { width: mobileWidth }]}>
    {header}
    {body}
  </View>;

  return narrow
    ? <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tableScroll}>{table}</ScrollView>
    : <View style={styles.tableScroll}>{table}</View>;
}

function TableLink({ label, url, onOpenUrl, colors, accessibilityLabel, icons }) {
  return <Pressable accessibilityRole="link" accessibilityLabel={accessibilityLabel || label}
    accessibilityHint={url} onPress={() => onOpenUrl?.(url)}
    style={({ pressed }) => [styles.tableLink, pressed && styles.pressed]}>
    <Text style={[styles.tableLinkText, { color: colors.link }]}>{label}</Text>
    {icons.externalLink ? <View style={[styles.tinyIcon, { fontSize: 12, color: colors.link }]}>
      <Icon spec={icons.externalLink} />
    </View> : null}
  </Pressable>;
}

export function ReleaseUpdateBanner({
  releaseTag,
  onDismiss,
  onViewWhatsNew,
  palette = {},
  labels = {},
}) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.banner, labels);
  if (!releaseTag) return null;
  return <View accessibilityLiveRegion="polite" style={[styles.banner, {
    backgroundColor: 'rgba(99, 102, 241, 0.1)', borderColor: 'rgba(99, 102, 241, 0.3)',
  }]}>
    <Text style={[styles.bannerText, { color: colors.textSecondary }]}>{format(copy.updated, { tag: releaseTag })}</Text>
    <InlineLink label={copy.whatsNew} onPress={onViewWhatsNew} colors={colors} />
    <Pressable accessibilityRole="button" accessibilityLabel={copy.dismiss}
      onPress={onDismiss} style={({ pressed }) => pressed && styles.pressed}>
      <Text style={[styles.dismissText, { color: colors.textMuted }]}>×</Text>
    </Pressable>
  </View>;
}

export function AboutOverviewCard({
  description,
  sponsorUrl = 'https://github.com/dannyvfilms?metadata_source=app-about-description',
  onOpenUrl,
  palette = {},
  labels = {},
  icons: suppliedIcons = {},
}) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.overview, labels);
  return <Section icon={suppliedIcons.info} title={copy.title} colors={colors}>
    <Text style={[styles.bodyCopy, { color: colors.textSecondary }]}>{description || copy.description}</Text>
    <Text style={[styles.metaCopy, { color: colors.textMuted }]}>{copy.support}{' '}
      <InlineLink label={copy.supportLink} onPress={() => onOpenUrl?.(sponsorUrl)}
        accessibilityLabel={`${copy.supportLink} (opens in a new tab)`} colors={colors} />.
    </Text>
  </Section>;
}

export function WhatsNewCard({ releases = [], releasesUrl, onOpenUrl, loading = false,
  palette = {}, labels = {}, icons: suppliedIcons = {} }) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.whatsNew, labels);
  const [openTag, setOpenTag] = useState(releases[0]?.tag || '');
  useEffect(() => {
    setOpenTag(current => current || releases[0]?.tag || '');
  }, [releases]);
  return <Section icon={suppliedIcons.info} title={copy.title} colors={colors}
    bodyStyle={styles.whatsNewBody} nativeID="whats-new">
    {releases.length ? <>
      {releases.map(release => {
        const open = openTag === release.tag;
        return <View key={release.tag} style={styles.release}>
          <Pressable accessibilityRole="button" accessibilityLabel={format(copy.releaseNotes, { tag: release.tag })}
            accessibilityState={{ expanded: open }}
            onPress={() => setOpenTag(open ? '' : release.tag)}
            style={({ pressed }) => [styles.releaseSummary, pressed && styles.pressed]}>
            <Text aria-hidden="true" style={[styles.releaseChevron, { color: colors.textMuted },
              open && { transform: [{ rotate: '90deg' }] }]}>▸</Text>
            <Text style={[styles.releaseTag, { color: colors.text }]}>{release.tag}</Text>
            {release.published ? <Text style={[styles.releaseDate, { color: colors.textMuted }]}>{release.published}</Text> : null}
            {release.installed ? <Badge label={copy.installed} size="sm" tone="green-soft" nowrap /> : null}
            {release.newer ? <Badge label={copy.newer} size="sm" tone="indigo-soft" nowrap /> : null}
          </Pressable>
          {open ? <View style={styles.releaseBody}>
            {release.highlights?.length ? <View style={styles.bulletList}>
              {release.highlights.map((item, index) => <View key={index} style={styles.bulletRow}>
                <Text style={[styles.bulletDot, { color: colors.textSecondary }]}>•</Text>
                <Text style={[styles.bulletText, { color: colors.textSecondary }]}>
                  {item.title ? <Text style={styles.bulletTitle}>{item.title}</Text> : null}
                  {item.title && item.text ? '—' : ''}
                  {item.text}
                </Text>
              </View>)}
            </View> : <Text style={[styles.metaCopy, { color: colors.textMuted }]}>{copy.noHighlights}</Text>}
            <InlineLink label={copy.releasePage} accessibilityLabel={format(copy.releasePageLabel, { tag: release.tag })}
              onPress={() => onOpenUrl?.(release.url)} colors={colors} style={styles.metaCopy} />
          </View> : null}
        </View>;
      })}
      <InlineLink label={copy.allReleases} onPress={() => onOpenUrl?.(releasesUrl)} colors={colors}
        style={styles.metaCopy} />
    </> : <Text style={[styles.metaCopy, { color: colors.textMuted }]}>
      {loading ? copy.loading : copy.empty}
    </Text>}
  </Section>;
}

function InstallSteps({ title, steps, colors }) {
  return <View style={[styles.stepCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
    <Text role="heading" aria-level={4} style={[styles.stepTitle, { color: colors.text }]}>{title}</Text>
    <View style={styles.stepList}>
      {steps.map((step, index) => <View key={step} style={styles.stepRow}>
        <Text style={[styles.stepText, { color: colors.textMuted }]}>{index + 1}.</Text>
        <Text style={[styles.stepText, { color: colors.textMuted }]}>{step}</Text>
      </View>)}
    </View>
  </View>;
}

export function InstallCard({
  installAvailable = false,
  installBusy = false,
  installStatus,
  platform = 'all',
  guideUrl = 'https://github.com/dannyvfilms/Floppy/wiki/2.-User-Guide#installing-floppy-on-your-phone',
  onInstall,
  onOpenUrl,
  palette = {},
  buttonPalette = {},
  labels = {},
  icons: suppliedIcons = {},
}) {
  const colors = useColors(palette);
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = mergeLabels(defaultLabels.install, labels);
  const { width } = useWindowDimensions();
  const showIos = platform === 'all' || platform === 'ios';
  const showAndroid = platform === 'all' || platform === 'android';
  const showGuideNote = platform === 'all' || platform === 'desktop';
  const twoColumns = showIos && showAndroid && width >= 640;
  return <Section icon={suppliedIcons.download} title={copy.title} colors={colors}
    bodyStyle={styles.installBody}>
    <Text style={[styles.bodyCopy, { color: colors.textSecondary }]}>{copy.intro}</Text>
    {installAvailable ? <View style={styles.action}>
      <Button label={copy.install} busy={installBusy} onPress={onInstall} palette={buttons} width="auto" />
    </View> : null}
    {installStatus ? <Text accessibilityLiveRegion="polite"
      style={[styles.metaCopy, { color: colors.textMuted }]}>{installStatus}</Text> : null}
    {showIos || showAndroid ? <View style={[styles.stepGrid, twoColumns && styles.stepGridTwo]}>
      {showIos ? <InstallSteps title={copy.iosTitle} steps={copy.iosSteps} colors={colors} /> : null}
      {showAndroid ? <InstallSteps title={copy.androidTitle} steps={copy.androidSteps} colors={colors} /> : null}
    </View> : null}
    {showGuideNote ? <Text style={[styles.metaCopy, { color: colors.textMuted }]}>
      {copy.guidePrefix}{' '}
      <InlineLink label={copy.guideLink} onPress={() => onOpenUrl?.(guideUrl)}
        accessibilityLabel={`${copy.guideLink} (opens in a new tab)`} colors={colors} />{' '}
      {copy.guideSuffix}
    </Text> : null}
    <Text style={[styles.metaCopy, { color: colors.textMuted }]}>{copy.noControl}{' '}
      <InlineLink label={copy.guideLabel} onPress={() => onOpenUrl?.(guideUrl)}
        accessibilityLabel={`${copy.guideLabel} (opens in a new tab)`} colors={colors} />
    </Text>
  </Section>;
}

export function ProjectResourcesCard({ resources = [], onOpenUrl, palette = {}, labels = {},
  icons: suppliedIcons = {} }) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.resources, labels);
  const iconKeys = ['globe', 'github', 'bookOpen', 'bug', 'persons', 'heart'];
  const rows = resources.map((item, index) => ({
    key: item.label,
    cells: [
      <View style={styles.resourceName}>
        {suppliedIcons[iconKeys[index]] ? <View style={[styles.rowIcon, { fontSize: 16, color: colors.link }]}>
          <Icon spec={suppliedIcons[iconKeys[index]]} />
        </View> : null}
        <Text style={[styles.rowName, { color: colors.text }]}>{item.label}</Text>
      </View>,
      <Text style={[styles.rowMeta, { color: colors.textMuted }]}>{item.description}</Text>,
      <TableLink label={item.action || defaultLabels.links.open} url={item.url}
        onOpenUrl={onOpenUrl} colors={colors} icons={suppliedIcons}
        accessibilityLabel={`${item.action || defaultLabels.links.open} (opens in a new tab)`} />,
    ],
  }));
  return <Section icon={suppliedIcons.externalLink} title={copy.title} colors={colors}>
    <DataTable columns={copy.columns} rows={rows} widths={[0.227, 0.613, 0.16]}
      mobileWidths={[157, 122.1, 120.9]} mobileWidth={400} colors={colors}
      testID="about-resources-table" />
  </Section>;
}

function FormatBadge({ label, colors }) {
  return <View style={[styles.formatBadge, {
    backgroundColor: colors.surfaceMuted, borderColor: colors.border,
  }]}>
    <Text style={[styles.formatBadgeText, { color: colors.textMuted }]}>{label}</Text>
  </View>;
}

function SpecActions({ spec, copy, colors, onOpenUrl, onPreview, onDownload, icons }) {
  const open = onOpenUrl ? () => onOpenUrl(spec.url) : undefined;
  const preview = onPreview && spec.downloadName ? () => onPreview(spec) : undefined;
  const download = onDownload && spec.downloadName ? () => onDownload(spec) : undefined;
  if (!preview && !download) {
    return <Pressable accessibilityRole="link" accessibilityLabel={spec.actionLabel || copy.openDocs || copy.open}
      onPress={open} style={({ pressed }) => [styles.actionButton, {
        backgroundColor: colors.surfaceStrong, borderColor: colors.border,
      }, pressed && styles.pressed]}>
      <Text style={[styles.actionButtonText, { color: colors.text }]}>{spec.actionLabel || copy.openDocs || copy.open}</Text>
    </Pressable>;
  }
  return <View style={styles.specActions}>
    {preview ? <Pressable accessibilityRole="button" accessibilityLabel={format(copy.previewLabel, { label: spec.label })}
      onPress={preview} style={({ pressed }) => [styles.actionButton, {
        backgroundColor: colors.surfaceStrong, borderColor: colors.border,
      }, pressed && styles.pressed]}>
      <Text style={[styles.actionButtonText, { color: colors.text }]}>{copy.preview}</Text>
    </Pressable> : null}
    {download ? <Pressable accessibilityRole="link" accessibilityLabel={format(copy.downloadLabel, { label: spec.label })}
      onPress={download} style={({ pressed }) => [styles.actionButton, {
        backgroundColor: colors.surfaceStrong, borderColor: colors.border,
      }, pressed && styles.pressed]}>
      {icons.download ? <View style={[styles.actionIcon, { fontSize: 14, color: colors.text }]}>
        <Icon spec={icons.download} />
      </View> : null}
      <Text style={[styles.actionButtonText, { color: colors.text }]}>{copy.download}</Text>
    </Pressable> : null}
  </View>;
}

export function DeveloperSpecsCard({ specs = [], onOpenUrl, onPreview, onDownload,
  palette = {}, labels = {}, icons: suppliedIcons = {} }) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.specs, labels);
  const rows = specs.map((spec, index) => ({
    key: spec.label,
    cells: [
      <View style={styles.specNameBlock}>
        <Pressable accessibilityRole="link" accessibilityLabel={spec.label}
          accessibilityHint={spec.url} onPress={() => onOpenUrl?.(spec.url)}
          style={({ pressed }) => [styles.specLink, pressed && styles.pressed]}>
          {suppliedIcons[index === 0 ? 'bookOpen' : 'page'] ? <View style={[styles.rowIcon, { fontSize: 16, color: colors.link }]}>
            <Icon spec={suppliedIcons[index === 0 ? 'bookOpen' : 'page']} />
          </View> : null}
          <Text style={[styles.specLinkText, { color: colors.link }]}>{spec.label}</Text>
        </Pressable>
        {spec.description ? <Text style={[styles.specDescription, { color: colors.textMuted }]}>{spec.description}</Text> : null}
      </View>,
      <FormatBadge label={spec.format} colors={colors} />,
      <SpecActions spec={spec} copy={copy} colors={colors}
        onOpenUrl={onOpenUrl} onPreview={onPreview} onDownload={onDownload} icons={suppliedIcons} />,
    ],
  }));
  return <Section icon={suppliedIcons.page} title={copy.title} colors={colors}>
    <DataTable columns={copy.columns} rows={rows} widths={[0.524, 0.233, 0.243]}
      mobileWidths={[150.2, 103.4, 129.2]} mobileWidth={382.8} colors={colors}
      testID="about-specs-table" />
  </Section>;
}

export function AttributionsCard({ attributions = [], onOpenUrl, palette = {}, labels = {},
  icons: suppliedIcons = {} }) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.attributions, labels);
  const rows = attributions.map(item => ({
    key: item.provider,
    cells: [
      <Text style={[styles.rowName, { color: colors.text }]}>{item.provider}</Text>,
      <Text style={[styles.rowMeta, { color: colors.textMuted }]}>{item.media}</Text>,
      <TableLink label={item.action || copy.open} url={item.url} onOpenUrl={onOpenUrl}
        colors={colors} icons={suppliedIcons}
        accessibilityLabel={`${item.action || copy.open} (opens in a new tab)`} />,
    ],
  }));
  return <Section icon={suppliedIcons.page} title={copy.title} colors={colors}>
    <DataTable columns={copy.columns} rows={rows} widths={[0.298, 0.493, 0.209]}
      mobileWidths={[126.1, 122.9, 139.1]} mobileWidth={388.1} colors={colors}
      testID="about-attributions-table" />
  </Section>;
}

export function LicenseCard({ licenses = [], onOpenUrl, palette = {}, labels = {},
  icons: suppliedIcons = {} }) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.licenses, labels);
  const rows = licenses.map(item => ({
    key: item.subject,
    cells: [
      <Text style={[styles.rowName, { color: colors.text }]}>{item.subject}</Text>,
      <Text style={[styles.rowMeta, { color: colors.textMuted }]}>{item.terms}</Text>,
      <TableLink label={item.action || copy.open} url={item.url} onOpenUrl={onOpenUrl}
        colors={colors} icons={suppliedIcons}
        accessibilityLabel={`${item.action || copy.open} (opens in a new tab)`} />,
    ],
  }));
  return <Section icon={suppliedIcons.page} title={copy.title} colors={colors}>
    <DataTable columns={copy.columns} rows={rows} widths={[0.245, 0.567, 0.189]}
      mobileWidths={[106.5, 94.8, 88.4]} mobileWidth={289.7} colors={colors}
      testID="about-licenses-table" />
  </Section>;
}

export function AboutVersionFooter({ version, commit, palette = {}, labels = {} }) {
  const colors = useColors(palette);
  const copy = mergeLabels(defaultLabels.version, labels);
  return <View style={[styles.version, { borderColor: colors.border }]}>
    <Text style={[styles.metaCopy, { color: colors.textMuted }]}>{copy.version}{' '}
      <Text style={styles.mono}>{version || copy.unavailable}</Text>{commit ? <>
        {' '}<Text style={{ color: colors.textMuted }}>|</Text> {copy.commit}{' '}
        <Text style={styles.mono}>{commit}</Text>
      </> : null}
    </Text>
  </View>;
}

const styles = StyleSheet.create({
  section: { gap: 12, minWidth: 0 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: 8, minWidth: 0 },
  headingIcon: { width: 20, height: 20, alignItems: 'center', justifyContent: 'center' },
  headingText: { fontSize: 18, lineHeight: 28, fontWeight: '500', flexShrink: 1 },
  sectionBody: { marginLeft: 28, gap: 12, minWidth: 0 },
  bodyCopy: { fontSize: 16, lineHeight: 26 },
  metaCopy: { fontSize: 14, lineHeight: 21 },
  inlineLink: { fontSize: 14, lineHeight: 21, textDecorationLine: 'underline' },
  banner: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 8 },
  bannerText: { flexGrow: 1, flexShrink: 1, fontSize: 14, lineHeight: 20 },
  dismissText: { fontSize: 18, fontWeight: '600', paddingHorizontal: 4 },
  pressed: { opacity: 0.75 },
  whatsNewBody: { gap: 24 },
  release: { gap: 8 },
  releaseSummary: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  releaseChevron: { fontSize: 12, lineHeight: 16 },
  releaseTag: { fontFamily: 'Courier', fontSize: 16, lineHeight: 24 },
  releaseDate: { fontSize: 12, lineHeight: 16 },
  releaseBody: { gap: 8, paddingTop: 8 },
  bulletList: { gap: 4, paddingLeft: 20 },
  bulletRow: { flexDirection: 'row', gap: 6, minWidth: 0 },
  bulletDot: { fontSize: 14, lineHeight: 21 },
  bulletText: { fontSize: 14, lineHeight: 21, flexShrink: 1 },
  bulletTitle: { fontWeight: '500' },
  installBody: { gap: 16 },
  stepGrid: { gap: 16 },
  stepGridTwo: { flexDirection: 'row', alignItems: 'stretch' },
  stepCard: { flex: 1, gap: 8, borderWidth: 1, borderRadius: 6, padding: 16, minWidth: 0 },
  stepTitle: { fontSize: 14, lineHeight: 20, fontWeight: '600' },
  stepList: { gap: 4, paddingLeft: 16 },
  stepRow: { flexDirection: 'row', gap: 6 },
  stepText: { fontSize: 14, lineHeight: 21, flexShrink: 1 },
  action: { alignSelf: 'flex-start' },
  tableScroll: { minWidth: 0 },
  table: { borderWidth: 1, overflow: 'hidden', width: '100%' },
  tableHead: { flexDirection: 'row', borderBottomWidth: 1 },
  tableRow: { flexDirection: 'row' },
  headCell: { paddingHorizontal: 16, paddingVertical: 12, minWidth: 0 },
  headText: { fontSize: 12, lineHeight: 16, fontWeight: '600', letterSpacing: 0.6, textTransform: 'uppercase' },
  cell: { paddingHorizontal: 16, paddingVertical: 12, minWidth: 0, justifyContent: 'center' },
  cellRight: { alignItems: 'flex-end' },
  rowName: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  rowMeta: { fontSize: 12, lineHeight: 16 },
  resourceName: { flexDirection: 'row', alignItems: 'center', gap: 8, minWidth: 0 },
  rowIcon: { width: 16, height: 16, alignItems: 'center', justifyContent: 'center' },
  tableLink: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  tableLinkText: { fontSize: 12, lineHeight: 16, fontWeight: '500' },
  tinyIcon: { width: 12, height: 12, alignItems: 'center', justifyContent: 'center' },
  specNameBlock: { gap: 2, minWidth: 0 },
  specLink: { flexDirection: 'row', alignItems: 'center', gap: 8, minWidth: 0 },
  specLinkText: { fontSize: 14, lineHeight: 20, fontWeight: '500', flexShrink: 1 },
  specDescription: { fontSize: 12, lineHeight: 16 },
  formatBadge: { alignSelf: 'flex-start', borderWidth: 1, borderRadius: 4, paddingHorizontal: 8, paddingVertical: 2 },
  formatBadgeText: { fontSize: 12, lineHeight: 16, fontFamily: 'Courier' },
  specActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, justifyContent: 'flex-end' },
  actionButton: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: 4, paddingHorizontal: 10, paddingVertical: 4 },
  actionButtonText: { fontSize: 12, lineHeight: 16, fontWeight: '500' },
  actionIcon: { width: 14, height: 14, alignItems: 'center', justifyContent: 'center' },
  version: { borderTopWidth: 1, paddingTop: 16 },
  mono: { fontFamily: 'Courier' },
});
