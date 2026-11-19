import { Platform, StatusBar } from 'react-native';

// Android does not include the status bar in SafeAreaView's inset.
export const statusBarInset = Platform.OS === 'android' ? StatusBar.currentHeight || 0 : 0;
