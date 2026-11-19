import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { inlineMarkdown, markdownBlocks } from './markdown';

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  border: '#52525b',
  link: '#818cf8',
  codeBackground: '#1f2328',
  codeText: '#e4e4e7',
};

const HEADING_SIZE = { 1: 21, 2: 19, 3: 17, 4: 15, 5: 14, 6: 13 };

function inlineTokens(text, style, palette, keyPrefix) {
  return inlineMarkdown(text).map((token, index) => {
    const key = `${keyPrefix}-${index}`;
    if (token.type === 'bold') {
      return <Text key={key} style={[style, styles.bold]}>{token.text}</Text>;
    }
    if (token.type === 'italic') {
      return <Text key={key} style={[style, styles.italic]}>{token.text}</Text>;
    }
    if (token.type === 'code') {
      return <Text key={key}
        style={[style, styles.inlineCode, { backgroundColor: palette.codeBackground, color: palette.codeText }]}>
        {token.text}
      </Text>;
    }
    if (token.type === 'link') {
      return <Text key={key}
        accessibilityRole="link"
        accessibilityLabel={token.href ? `${token.text}: ${token.href}` : token.text}
        style={[style, { color: palette.link, textDecorationLine: 'underline' }]}>
        {token.text}
      </Text>;
    }
    return <Text key={key} style={style}>{token.text}</Text>;
  });
}

export function MarkdownPreview({ markdown, labels = {}, palette: suppliedPalette }) {
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const source = String(markdown ?? '');
  const blocks = markdownBlocks(source);
  if (!blocks.length) {
    return <Text style={[styles.empty, { color: palette.textMuted }]}>
      {labels.emptyPreview || 'Nothing to preview yet.'}
    </Text>;
  }
  return <View style={styles.root}>
    {blocks.map((block, index) => {
      const key = `block-${index}`;
      if (block.type === 'heading') {
        const size = HEADING_SIZE[block.level] || 14;
        return <Text key={key} accessibilityRole="header"
          style={[styles.heading, { color: palette.text, fontSize: size, lineHeight: size + 6 }]}>
          {inlineTokens(block.text, { color: palette.text, fontSize: size, lineHeight: size + 6 }, palette, key)}
        </Text>;
      }
      if (block.type === 'code') {
        return <View key={key} style={[styles.codeBlock, { backgroundColor: palette.codeBackground }]}>
          <Text style={[styles.codeText, { color: palette.codeText }]}>{block.text || ' '}</Text>
        </View>;
      }
      if (block.type === 'hr') {
        return <View key={key} style={[styles.hr, { backgroundColor: palette.border }]} />;
      }
      if (block.type === 'quote') {
        return <View key={key} style={[styles.quote, { borderLeftColor: palette.border }]}>
          <Text style={[styles.quoteText, { color: palette.textSecondary }]}>
            {inlineTokens(block.text, { color: palette.textSecondary }, palette, key)}
          </Text>
        </View>;
      }
      if (block.type === 'list') {
        return <View key={key} style={styles.list}>
          {block.items.map((item, itemIndex) => {
            const itemKey = `${key}-${itemIndex}`;
            return <View key={itemKey} style={styles.listRow}>
              <Text style={[styles.bullet, { color: palette.textMuted }]}>
                {block.ordered ? `${itemIndex + 1}.` : '•'}
              </Text>
              <Text style={[styles.listText, { color: palette.textSecondary }]}>
                {inlineTokens(item, { color: palette.textSecondary }, palette, itemKey)}
              </Text>
            </View>;
          })}
        </View>;
      }
      return <Text key={key} style={[styles.paragraph, { color: palette.textSecondary }]}>
        {inlineTokens(block.text, { color: palette.textSecondary }, palette, key)}
      </Text>;
    })}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 8 },
  empty: { fontSize: 13 },
  heading: { fontWeight: '700' },
  paragraph: { fontSize: 13, lineHeight: 20 },
  bold: { fontWeight: '700' },
  italic: { fontStyle: 'italic' },
  inlineCode: { fontSize: 12, borderRadius: 4, paddingHorizontal: 4 },
  codeBlock: { borderRadius: 6, padding: 10 },
  codeText: { fontSize: 12, lineHeight: 17, fontFamily: 'Courier' },
  hr: { height: 1, marginVertical: 4 },
  quote: { borderLeftWidth: 2, paddingLeft: 10 },
  quoteText: { fontSize: 13, lineHeight: 20, fontStyle: 'italic' },
  list: { gap: 4 },
  listRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
  bullet: { fontSize: 13, lineHeight: 20 },
  listText: { flex: 1, fontSize: 13, lineHeight: 20 },
});
