import React, { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { AdaptivePresentationSheet } from '../components/AdaptivePresentationSheet';

export default function SheetPreview() {
  const [open, setOpen] = useState(true);
  return <View style={{ flex: 1, backgroundColor: '#080808', padding: 32, justifyContent: 'center' }}>
    <Text style={{ color: 'white', fontSize: 26, fontWeight: '600', marginBottom: 20 }}>Sheet preview</Text>
    <Pressable accessibilityRole="button" onPress={() => setOpen(true)} style={{ padding: 16, backgroundColor: '#292929', borderRadius: 14 }}>
      <Text style={{ color: 'white', fontSize: 18 }}>Open sheet</Text>
    </Pressable>
    <AdaptivePresentationSheet isPresented={open} onDismiss={() => setOpen(false)} onClose={() => setOpen(false)} title="Usage" containerColor="#111111">
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 24, paddingBottom: 48 }}>
        {['Context', 'Plan usage', 'Weekly limits', 'Limit resets'].map((title, index) => <View key={title} style={{ marginBottom: 30 }}>
          <Text style={{ color: '#a4a29c', fontSize: 18, marginBottom: 12 }}>{title}</Text>
          <View style={{ backgroundColor: '#1d1d1d', borderRadius: 24, padding: 24, minHeight: 120 }}>
            <Text style={{ color: 'white', fontSize: 22 }}>{['Context window', 'Current session', 'All models', 'No resets right now'][index]}</Text>
            {index < 3 && <View style={{ height: 8, borderRadius: 4, backgroundColor: '#09284f', marginTop: 16 }}><View style={{ width: '42%', height: 8, backgroundColor: '#3785e6', borderRadius: 4 }} /></View>}
            <Text style={{ color: '#a4a29c', fontSize: 16, marginTop: 12 }}>{index === 0 ? '127.8K of 1M tokens' : 'Preview content'}</Text>
          </View>
        </View>)}
      </ScrollView>
    </AdaptivePresentationSheet>
  </View>;
}
