// Let Metro resolve the shared API client from ../packages.
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, "..");
const config = getDefaultConfig(projectRoot);
config.watchFolders = [path.join(monorepoRoot, "packages")];
config.resolver.nodeModulesPaths = [path.join(projectRoot, "node_modules")];
module.exports = config;
