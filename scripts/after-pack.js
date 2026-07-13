/**
 * After electron-builder packs win-unpacked:
 * Embed BBico.ico into BotBuilder.exe (replaces default Electron icon).
 * Icon is not copied to the install folder — it lives only inside the .exe.
 */
const path = require("path");
const fs = require("fs");

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "win32") return;

  const exeName = `${context.packager.appInfo.productFilename}.exe`;
  const exePath = path.join(context.appOutDir, exeName);
  const iconSrc = path.join(context.packager.projectDir, "BBico.ico");

  if (!fs.existsSync(exePath)) {
    throw new Error(`[afterPack] exe not found: ${exePath}`);
  }
  if (!fs.existsSync(iconSrc)) {
    throw new Error(`[afterPack] icon not found: ${iconSrc}`);
  }

  const rcedit = require("rcedit");
  await rcedit(exePath, {
    icon: iconSrc,
    "version-string": {
      CompanyName: "BotBuilder",
      FileDescription: "BotBuilder",
      ProductName: "BotBuilder",
      LegalCopyright: "Copyright © BotBuilder",
    },
  });
  console.log("[afterPack] embedded icon into", exePath);
};
