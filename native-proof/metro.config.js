const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
// Resolve the shared source using this app's single React and React Native pair.
config.watchFolders = [path.resolve(__dirname, '..')];
config.resolver.disableHierarchicalLookup = true;
config.resolver.nodeModulesPaths = [path.resolve(__dirname, 'node_modules')];
// Generated Xcode sources and build products are not JavaScript inputs.
config.resolver.blockList = [config.resolver.blockList, /native-proof\/ios\/.*/].flat().filter(Boolean);
module.exports = config;
