import React from 'react';
import { Linking, StyleSheet, View } from 'react-native';
import { ErrorsView } from '../../../frontend/pages/ErrorsView';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { ERROR_PAGES, errorPageWithMessage, ISSUES_URL } from '../data/errorPages';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'ERROR',
  status: 'ported',
  title: 'Error pages',
  where: '400, 403, 404, 500 and server-unreachable states',
  note: 'Renders the shared error recovery view with the server error-page wording. Reached through the stack route ErrorDocs with { status } or { error }, and by the app error boundary in the shell.',
};

const errorPalette = {
  ...palette,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  focusStyle: {},
};

// One error page: `status` picks a server page (400, 403, 404, 500, offline) and
// `error` maps a failed request onto one. `onRetry` is shown only when the
// caller can repeat the work.
export function ErrorPage({ status, error, onRetry, onGoHome }) {
  const page = error ? errorPageWithMessage(error) : (ERROR_PAGES[status] || ERROR_PAGES[500]);
  const server = getActiveAuthSession()?.serverUrl || '';
  const report = [
    `Status: ${page.status}`,
    `Page: ${page.heading}`,
    `Message: ${page.message}`,
    server ? `Server: ${server}` : '',
    `Time: ${new Date().toISOString()}`,
  ].filter(Boolean).join('\n');
  return <ErrorsView
    error={{
      report,
      reportTitle: 'Diagnostics',
      reportNote: 'Select this block when opening a ticket so the request details are preserved.',
      status: page.status,
      heading: page.heading,
      message: page.message,
      checks: page.checks || [],
      onRetry,
      onGoHome,
      onReportIssue: () => { Linking.openURL(ISSUES_URL).catch(() => {}); },
    }}
    palette={errorPalette}
  />;
}

export default function ErrorDocsScreen({ params, onBack, navigate }) {
  return <Screen onBack={onBack} chrome={false} contentStyle={styles.content}>
    <View style={styles.page}>
      <ErrorPage status={params?.status} error={params?.error} onRetry={params?.onRetry}
        onGoHome={onBack} />
    </View>
  </Screen>;
}

// Catches render failures in a screen so the shell stays usable.
export class ErrorBoundary extends React.Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <Screen chrome={false} contentStyle={styles.content}>
      <ErrorPage status={500} onRetry={() => this.setState({ failed: false })} onGoHome={this.props.onGoHome} />
    </Screen>;
  }
}

const styles = StyleSheet.create({
  content: { paddingTop: spacing.xl },
  page: { alignItems: 'center' },
});
