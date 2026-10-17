#!/usr/bin/env node
// Generates the native iOS / Android projects with Capacitor and applies Ops Tarot's settings.
// Safe to run again and again: every step checks first and only changes what is missing.
//
//   node scripts/setup.mjs            # Android (and iOS when run on a Mac)
//   node scripts/setup.mjs ios        # only iOS
//   node scripts/setup.mjs android    # only Android
//
// Optional environment variables:
//   APP_VERSION_NAME   shown in the stores, default: package.json "version"   (e.g. 0.9.0)
//   APP_VERSION_CODE   build number, must grow with every upload; default from the version (0.9.0 -> 900)
//   APPLE_TEAM_ID      your 10-character Apple Developer Team ID, written into the Xcode project
//   SKIP_ASSETS=1      do not regenerate icons and splash screens
import { execSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
const config = JSON.parse(readFileSync(join(ROOT, 'capacitor.config.json'), 'utf8'));
const HOSTS = config.server.allowNavigation;
const BG = config.backgroundColor;

const versionName = process.env.APP_VERSION_NAME || pkg.version;
const [maj = 0, min = 0, pat = 0] = versionName.split('.').map(n => parseInt(n, 10) || 0);
const versionCode = String(process.env.APP_VERSION_CODE || maj * 10000 + min * 100 + pat);
if (!/^[1-9]\d{0,8}$/.test(versionCode)) fail(`APP_VERSION_CODE must be a positive whole number, got "${versionCode}"`);

function fail(msg) { console.error(`\n✗ ${msg}\n`); process.exit(1); }
function run(cmd) { console.log(`$ ${cmd}`); execSync(cmd, { cwd: ROOT, stdio: 'inherit' }); }
function edit(file, fn) {
  const path = join(ROOT, file);
  if (!existsSync(path)) fail(`${file} not found — did "npx cap add" succeed?`);
  const before = readFileSync(path, 'utf8'), after = fn(before);
  if (after !== before) { writeFileSync(path, after); console.log(`  patched ${file}`); }
}
function must(text, re, what) { if (!re.test(text)) fail(`Cannot find ${what}. The Capacitor template may have changed; please update scripts/setup.mjs.`); }

// ---------------------------------------------------------------- Android
function patchAndroid() {
  const appLinks = `
            <!-- Ops Tarot: open honeytime.life links in the app (Android App Links) -->
            <intent-filter android:autoVerify="true">
                <action android:name="android.intent.action.VIEW" />
                <category android:name="android.intent.category.DEFAULT" />
                <category android:name="android.intent.category.BROWSABLE" />
                <data android:scheme="https" />
${HOSTS.map(h => `                <data android:host="${h}" />`).join('\n')}
            </intent-filter>
`;
  edit('android/app/src/main/AndroidManifest.xml', x => {
    if (!x.includes('Ops Tarot: open honeytime.life')) {
      must(x, /<\/activity>/, 'the main <activity> in AndroidManifest.xml');
      x = x.replace('</activity>', appLinks + '        </activity>');
    }
    if (!x.includes('android.permission.POST_NOTIFICATIONS'))
      x = x.replace(/(<manifest[^>]*>)/, '$1\n    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />');
    return x;
  });
  edit('android/app/build.gradle', x => {
    must(x, /versionCode\s*=?\s*[^\n]+/, 'versionCode in android/app/build.gradle');
    x = x.replace(/versionCode\s*=?\s*[^\n]+/, `versionCode ${versionCode}`)
         .replace(/versionName\s*=?\s*[^\n]+/, `versionName "${versionName}"`);
    if (!x.includes('ANDROID_KEYSTORE_PATH')) {
      must(x, /buildTypes\s*\{\s*release\s*\{/, 'buildTypes { release { in android/app/build.gradle');
      // Release signing comes from environment variables, so no password is ever stored in the project.
      x = x.replace(/(\n\s*)buildTypes\s*\{\s*release\s*\{/, `$1signingConfigs {
        release {
            if (System.getenv("ANDROID_KEYSTORE_PATH")) {
                storeFile file(System.getenv("ANDROID_KEYSTORE_PATH"))
                storePassword System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias System.getenv("ANDROID_KEY_ALIAS")
                keyPassword System.getenv("ANDROID_KEY_PASSWORD") ?: System.getenv("ANDROID_KEYSTORE_PASSWORD")
            }
        }
    }$1buildTypes {
        release {
            if (System.getenv("ANDROID_KEYSTORE_PATH")) {
                signingConfig signingConfigs.release
            }`);
    }
    return x;
  });
  edit('android/app/src/main/res/values/strings.xml', x =>
    x.replace(/<string name="app_name">[^<]*<\/string>/, `<string name="app_name">${config.appName}</string>`)
     .replace(/<string name="title_activity_main">[^<]*<\/string>/, `<string name="title_activity_main">${config.appName}</string>`));
}

// ---------------------------------------------------------------- iOS
function plistAdd(x, key, value) {
  if (x.includes(`<key>${key}</key>`)) return x;
  must(x, /<\/dict>\s*<\/plist>\s*$/, 'the end of Info.plist');
  return x.replace(/<\/dict>\s*<\/plist>\s*$/, `\t<key>${key}</key>\n\t${value}\n</dict>\n</plist>\n`);
}
function patchIOS() {
  edit('ios/App/App/Info.plist', x => {
    x = plistAdd(x, 'ITSAppUsesNonExemptEncryption', '<false/>');            // HTTPS only: no export paperwork
    x = plistAdd(x, 'CFBundleAllowMixedLocalizations', '<true/>');
    x = plistAdd(x, 'CFBundleLocalizations', '<array>\n\t\t<string>zh-Hans</string>\n\t\t<string>zh-Hant</string>\n\t\t<string>en</string>\n\t</array>');
    x = plistAdd(x, 'LSApplicationQueriesSchemes', '<array>\n\t\t<string>whatsapp</string>\n\t\t<string>weixin</string>\n\t\t<string>tg</string>\n\t</array>');
    x = x.replace(/(<key>CFBundleDisplayName<\/key>\s*<string>)[^<]*(<\/string>)/, `$1${config.appName}$2`);
    return x;
  });
  const entitlements = join(ROOT, 'ios/App/App/App.entitlements');
  writeFileSync(entitlements, `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>com.apple.developer.associated-domains</key>
\t<array>
${HOSTS.map(h => `\t\t<string>applinks:${h}</string>`).join('\n')}
\t\t<string>webcredentials:${HOSTS[0]}</string>
\t</array>
</dict>
</plist>
`);
  edit('ios/App/App.xcodeproj/project.pbxproj', x => {
    must(x, /INFOPLIST_FILE = App\/Info\.plist;/, 'INFOPLIST_FILE in project.pbxproj');
    if (!x.includes('CODE_SIGN_ENTITLEMENTS'))
      x = x.replace(/(\n(\s*)INFOPLIST_FILE = App\/Info\.plist;)/g, '\n$2CODE_SIGN_ENTITLEMENTS = App/App.entitlements;$1');
    // iPhone only: iPads still run it (in iPhone mode), and the store needs no iPad screenshots.
    x = x.replace(/TARGETED_DEVICE_FAMILY = "?[0-9,]+"?;/g, 'TARGETED_DEVICE_FAMILY = 1;');
    x = x.replace(/MARKETING_VERSION = [^;]+;/g, `MARKETING_VERSION = ${versionName};`)
         .replace(/CURRENT_PROJECT_VERSION = [^;]+;/g, `CURRENT_PROJECT_VERSION = ${versionCode};`);
    const team = (process.env.APPLE_TEAM_ID || '').trim().toUpperCase();
    if (team) {
      if (!/^[A-Z0-9]{10}$/.test(team)) fail('APPLE_TEAM_ID must be the 10-character Team ID from developer.apple.com → Membership');
      x = x.replace(/\n(\s*)DEVELOPMENT_TEAM = [^;]*;/g, '');
      x = x.replace(/(\n(\s*)INFOPLIST_FILE = App\/Info\.plist;)/g, '\n$2DEVELOPMENT_TEAM = ' + team + ';$1');
    }
    return x;
  });
}

// ---------------------------------------------------------------- main
const want = process.argv[2];
if (want && !['ios', 'android'].includes(want)) fail('usage: node scripts/setup.mjs [ios|android]');
const targets = want ? [want] : (process.platform === 'darwin' ? ['android', 'ios'] : ['android']);
if (targets.includes('ios') && process.platform !== 'darwin') fail('The iOS project can only be built on a Mac with Xcode.');
if (!existsSync(join(ROOT, 'node_modules/@capacitor/cli'))) run('npm install');
for (const t of targets) {
  if (!existsSync(join(ROOT, t))) run(`npx cap add ${t}`);
  if (process.env.SKIP_ASSETS !== '1')
    run(`npx capacitor-assets generate --${t} --iconBackgroundColor '${BG}' --iconBackgroundColorDark '${BG}' --splashBackgroundColor '${BG}' --splashBackgroundColorDark '${BG}'`);
  (t === 'android' ? patchAndroid : patchIOS)();
  run(`npx cap sync ${t}`);
}
console.log(`\n✓ Ready: ${targets.join(' + ')} · version ${versionName} (${versionCode})\n`);
