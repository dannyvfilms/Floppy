import React from 'react';
import { Platform, useColorScheme } from 'react-native';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import ThemeRoot from '../components/ThemeRoot';

export default function RootLayout() {
  const scheme = useColorScheme();
  const stack = <Stack screenOptions={{ headerShown: false, title: '' }} />;
  const themed = Platform.OS === 'ios' ? <ThemeProvider value={scheme === 'dark' ? DarkTheme : DefaultTheme}>{stack}</ThemeProvider> : stack;
  return <ThemeRoot>{themed}</ThemeRoot>;
}
