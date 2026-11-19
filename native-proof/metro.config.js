const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
// Resolve the shared source using this app's single React and React Native pair.
config.watchFolders = [path.resolve(__dirname, '..')];
config.resolver.disableHierarchicalLookup = true;
config.resolver.nodeModulesPaths = [path.resolve(__dirname, 'node_modules')];
// Generated Xcode sources and build products are not JavaScript inputs.
config.resolver.blockList = [config.resolver.blockList, /native-proof\/ios\/.*/].flat().filter(Boolean);
// Browser preview of the native variants. Without a simulator, the web build
// would pick the `.web.*` presentation adapters written for Django pages and
// their stylesheet. FLOPPY_PREVIEW_NATIVE=1 resolves shared presentation under
// frontend/ the way Android does (`.native.*`, then the plain file), rendered
// through react-native-web. Packages and data adapters still resolve for web.
if (process.env.FLOPPY_PREVIEW_NATIVE === '1') {
  const shared = `${path.resolve(__dirname, '..', 'frontend')}${path.sep}`;
  config.resolver.resolveRequest = (context, moduleName, platform) => {
    if (platform === 'web' && moduleName.startsWith('.') && !context.originModulePath.includes('node_modules')) {
      try {
        const native = context.resolveRequest({ ...context, preferNativePlatform: true }, moduleName, 'android');
        if (native.type === 'sourceFile' && native.filePath.startsWith(shared)) return native;
      } catch {
        // No native resolution: fall through to the web one.
      }
    }
    return context.resolveRequest(context, moduleName, platform);
  };
}
module.exports = config;
