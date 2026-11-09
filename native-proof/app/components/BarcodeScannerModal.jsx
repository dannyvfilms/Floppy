import { Modal, ModalCloseButton } from '../../../frontend/ui/Modal';
import React, { useEffect, useRef, useState } from 'react';
import {
  Linking,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import {
  BARCODE_TYPES,
  normalizeIsbn,
  pickBarcodePhoto,
} from '../../../frontend/ui/barcodeEntry';
import { palette, radius, spacing } from '../theme';

const defaultLabels = {
  title: 'Scan a book barcode',
  help: 'Point the camera at the ISBN barcode, or choose a photo. You can also type the ISBN.',
  cameraPermissionTitle: 'Camera access needed',
  cameraPermissionBody: 'Allow camera access to scan the barcode, or choose a photo or type the ISBN below.',
  allowCamera: 'Allow camera',
  openSettings: 'Open Settings',
  choosePhoto: 'Choose photo',
  manualLabel: 'ISBN',
  manualPlaceholder: 'Type an ISBN-10 or ISBN-13',
  manualAction: 'Use ISBN',
  cancel: 'Cancel',
  checking: 'Reading barcode…',
  invalidManual: 'Enter a valid ISBN-10 or ISBN-13.',
  notIsbn: 'That barcode is not an ISBN. Try a book barcode.',
  unreadable: 'Could not read a barcode from that photo. Try again or type the ISBN.',
  cameraError: 'The camera could not start. Choose a photo or type the ISBN.',
};

function messageFor(result, labels) {
  if (result?.status === 'unreadable') return labels.unreadable;
  return labels.notIsbn;
}

export function BarcodeScannerModal({
  visible,
  labels: labelOverrides,
  onCancel,
  onDecoded,
}) {
  const labels = { ...defaultLabels, ...(labelOverrides || {}) };
  const [permission, requestPermission] = useCameraPermissions();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState('');
  const scanned = useRef(false);
  const retryTimer = useRef(null);
  const requested = useRef(false);

  useEffect(() => {
    if (!visible) {
      requested.current = false;
      return;
    }
    setError(null);
    setBusy(false);
    setManual('');
    scanned.current = false;
  }, [visible]);

  useEffect(() => {
    if (!visible || !permission || permission.granted) return;
    if (!permission.canAskAgain || requested.current) return;
    requested.current = true;
    requestPermission();
  }, [permission, requestPermission, visible]);

  useEffect(() => () => clearTimeout(retryTimer.current), []);

  function finish(isbn) {
    if (scanned.current) return;
    scanned.current = true;
    onDecoded?.(isbn);
  }

  function handleScan(result) {
    if (!visible || scanned.current || busy) return;
    const isbn = normalizeIsbn(result?.data);
    if (isbn) {
      finish(isbn);
      return;
    }
    if (retryTimer.current) return;
    setError(labels.notIsbn);
    retryTimer.current = setTimeout(() => {
      retryTimer.current = null;
      setError(null);
    }, 1600);
  }

  async function choosePhoto() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await pickBarcodePhoto();
      if (result?.status === 'decoded' && result.isbn) finish(result.isbn);
      else if (result?.status === 'unreadable') setError(messageFor(result, labels));
    } catch (photoError) {
      setError(photoError?.message || labels.unreadable);
    } finally {
      setBusy(false);
    }
  }

  function useManual() {
    const isbn = normalizeIsbn(manual);
    if (!isbn) {
      setError(labels.invalidManual);
      return;
    }
    finish(isbn);
  }

  const permissionDenied = Boolean(permission && !permission.granted && !permission.canAskAgain);

  return <Modal
    visible={visible}
    animationType="slide"
    presentationStyle="fullScreen"
    onRequestClose={onCancel}
  >
    <View style={styles.root}>
      <View style={styles.header}>
        <View style={styles.heading}>
          <Text role="heading" aria-level={1} style={styles.title}>{labels.title}</Text>
          <Text style={styles.help}>{labels.help}</Text>
        </View>
        <ModalCloseButton accessibilityRole="button" accessibilityLabel={labels.cancel}
          onPress={onCancel} style={styles.close}>
          <Text style={styles.closeText}>×</Text>
        </ModalCloseButton>
      </View>

      <View style={styles.cameraFrame}>
        {permission?.granted
          ? <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: BARCODE_TYPES }}
            onBarcodeScanned={handleScan}
            onMountError={() => setError(labels.cameraError)}
          >
            <View style={styles.reticle} />
          </CameraView>
          : <View style={styles.permission}>
            <Text role="heading" aria-level={2} style={styles.permissionTitle}>
              {labels.cameraPermissionTitle}
            </Text>
            <Text style={styles.permissionBody}>{labels.cameraPermissionBody}</Text>
            {permission?.canAskAgain ? <Pressable accessibilityRole="button"
              onPress={() => requestPermission()}
              style={styles.primaryButton}>
              <Text style={styles.primaryText}>{labels.allowCamera}</Text>
            </Pressable> : null}
            {permissionDenied ? <Pressable accessibilityRole="button"
              onPress={() => Linking.openSettings()}
              style={styles.secondaryButton}>
              <Text style={styles.secondaryText}>{labels.openSettings}</Text>
            </Pressable> : null}
          </View>}
        {busy ? <View style={styles.scrim}>
          <Text accessibilityLiveRegion="polite" style={styles.scrimText}>{labels.checking}</Text>
        </View> : null}
      </View>

      {error ? <Text accessibilityLiveRegion="polite" role="alert" style={styles.error}>{error}</Text> : null}

      <View style={styles.actions}>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.choosePhoto}
          disabled={busy} onPress={choosePhoto}
          style={[styles.secondaryButton, busy && styles.disabled]}>
          <Text style={styles.secondaryText}>{labels.choosePhoto}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.cancel}
          onPress={onCancel} style={styles.secondaryButton}>
          <Text style={styles.secondaryText}>{labels.cancel}</Text>
        </Pressable>
      </View>

      <View style={styles.manual}>
        <Text style={styles.manualLabel}>{labels.manualLabel}</Text>
        <TextInput
          accessibilityLabel={labels.manualLabel}
          value={manual}
          onChangeText={setManual}
          placeholder={labels.manualPlaceholder}
          placeholderTextColor={palette.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="numbers-and-punctuation"
          returnKeyType="done"
          onSubmitEditing={useManual}
          style={styles.input}
        />
        <Pressable accessibilityRole="button" accessibilityLabel={labels.manualAction}
          onPress={useManual} style={styles.primaryButton}>
          <Text style={styles.primaryText}>{labels.manualAction}</Text>
        </Pressable>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.background, paddingTop: 56, paddingBottom: 24, gap: spacing.md },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, paddingHorizontal: spacing.lg },
  heading: { flex: 1, gap: 4 },
  title: { color: palette.text, fontSize: 22, fontWeight: '700' },
  help: { color: palette.textMuted, fontSize: 13, lineHeight: 18 },
  close: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, backgroundColor: palette.surface },
  closeText: { color: palette.text, fontSize: 24, lineHeight: 26 },
  cameraFrame: { flex: 1, minHeight: 260, backgroundColor: palette.surface, overflow: 'hidden' },
  reticle: {
    position: 'absolute',
    left: '10%',
    right: '10%',
    top: '35%',
    height: '30%',
    borderWidth: 2,
    borderColor: 'rgba(255, 255, 255, 0.85)',
    borderRadius: radius.md,
  },
  permission: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm, padding: spacing.xl },
  permissionTitle: { color: palette.text, fontSize: 18, fontWeight: '600', textAlign: 'center' },
  permissionBody: { color: palette.textMuted, fontSize: 13, lineHeight: 19, textAlign: 'center', maxWidth: 420 },
  scrim: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(24, 24, 27, 0.72)' },
  scrimText: { color: palette.text, fontSize: 14, fontWeight: '600' },
  error: { color: palette.danger, fontSize: 13, lineHeight: 18, paddingHorizontal: spacing.lg },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, paddingHorizontal: spacing.lg },
  secondaryButton: { borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface, borderRadius: radius.sm, paddingHorizontal: 14, paddingVertical: 10 },
  secondaryText: { color: palette.textSecondary, fontSize: 13, fontWeight: '600' },
  disabled: { opacity: 0.5 },
  manual: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: palette.border },
  manualLabel: { color: palette.textSecondary, fontSize: 12, fontWeight: '600' },
  input: { borderWidth: 1, borderColor: palette.border, borderRadius: radius.sm, backgroundColor: palette.surface, color: palette.text, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  primaryButton: { alignSelf: 'flex-start', borderRadius: radius.sm, backgroundColor: palette.accent, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: '#ffffff', fontSize: 13, fontWeight: '700' },
});
