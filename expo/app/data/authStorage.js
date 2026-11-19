import * as SecureStore from 'expo-secure-store';

const secureOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export const secureStorage = {
  getItem(key) {
    return SecureStore.getItemAsync(key);
  },
  setItem(key, value) {
    return SecureStore.setItemAsync(key, value, secureOptions);
  },
  removeItem(key) {
    return SecureStore.deleteItemAsync(key);
  },
};
