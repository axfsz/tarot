# 奥普塔罗 App（iOS / 安卓）

这个目录是手机 App 的工程，用 [Capacitor 8](https://capacitorjs.com) 打包。

## 它是怎么工作的

- App 是一个原生“外壳”，打开后直接加载 `https://honeytime.life`。所有页面、账号、抽牌、解读、预约都和网站是同一套。
- **网站更新后，App 里的内容立刻跟着更新**，不用重新提交商店审核。只有改了本目录（原生功能、图标、版本号）才需要重新打包上架。
- 外壳额外提供了网页做不到的原生能力（也是苹果审核看重的）：
  - **每日一牌提醒**：手机本地通知，在“我的记录”页面设置时间；第一次在 App 里抽完今日牌时会询问一次。
  - **原生分享面板**：案例页“分享”调用系统分享。
  - **触感反馈**：抽牌时手机轻微震动。
  - **点网址直接打开 App**（Universal Links / App Links）：别人发来的 honeytime.life 链接会在 App 里打开。
  - **离线页**：没有网络时显示品牌离线页，联网后一键重连。
  - **外部链接**（WhatsApp、付款链接等）在 App 内浏览器打开，不会把 App 跳走。
  - 安卓返回键：先关菜单，再返回上一页，在首页时退出。
- 服务器通过 User-Agent 里的 `OpsTarotApp/ios`、`OpsTarotApp/android` 识别 App，按商店规则调整（见下文“iOS 收费规则”）。

## 第 0 步：先更新服务器到 v0.9.0

App 依赖 v0.9.0 新增的接口（注销账号、举报/屏蔽评价、深链文件），所以**先部署网站，再提交 App 审核**。

## 安卓

### 1. 先装个测试版看看（不用任何账号）

每次推送到 GitHub，Actions 都会自动打包：

1. 打开仓库 → **Actions** → 左侧 **CI** → 点最新一次运行。
2. 页面底部 **Artifacts** 里下载 `android-app`，解压得到 `ops-tarot-debug.apk`。
3. 发到安卓手机上打开安装（需要允许“安装未知来源应用”）。

### 2. 正式签名（上架和对外分发都需要）

签名密钥只生成一次，**务必备份**：丢了以后就无法再更新这个 App。

在 Mac 终端执行（会提示设置密码，记下来）：

```bash
keytool -genkeypair -v -keystore ops-tarot-release.jks -alias opstarot \
  -keyalg RSA -keysize 4096 -validity 36500 \
  -dname "CN=Ops Tarot Studio, O=Ops Global Online, C=MY"
base64 -i ops-tarot-release.jks | pbcopy   # 把密钥转成文本，已复制到剪贴板
```

到 GitHub 仓库 → **Settings → Secrets and variables → Actions → New repository secret**，添加 4 个：

| 名称 | 内容 |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | 刚才复制的那一长串文本 |
| `ANDROID_KEYSTORE_PASSWORD` | 密钥库密码 |
| `ANDROID_KEY_ALIAS` | `opstarot` |
| `ANDROID_KEY_PASSWORD` | 密钥密码（和上面相同就填相同的） |

之后每次构建都会额外产出已签名的 `ops-tarot.apk`（直接安装用）和 `ops-tarot.aab`（上传 Google Play 用），以及 `SHA256.txt`。

### 3. 开启“点网址打开 App”

把 `SHA256.txt` 里的指纹填进服务器 `.env`：

```bash
APP_ANDROID_SHA256=AB:CD:...    # 上架 Google Play 后，再加上 Play 后台“应用签名”页的 SHA-256，用英文逗号隔开
```

然后 `docker compose up -d --force-recreate app`。打开 `https://honeytime.life/.well-known/assetlinks.json` 能看到内容就说明生效了。

### 4. 发布

- **网站直接下载**：给代码打一个标签，例如 `git tag app-v0.9.0 && git push origin app-v0.9.0`。Actions 会自动建一个 GitHub Release，附上已签名的 `ops-tarot.apk`，可以把下载链接放到网站或社媒主页上。
- **Google Play**：
  - 注册开发者账号（一次性 25 美元）。
  - 新建应用，上传 `ops-tarot.aab`。
  - 注意：**2023 年 11 月后注册的个人开发者账号**，需要先做“封闭测试”（至少 12 名测试者、连续 14 天），才能申请正式发布。可以先拉朋友和老客户进测试组。
- **国内安卓商店**（华为、小米、OPPO、vivo、应用宝）：都要求**软件著作权**和**App 备案**（ICP），部分商店还要求企业主体。这些材料准备好后，用同一个已签名 APK 提交即可。

## iOS（在你的 Mac 上）

需要：Xcode 26 或更新（App Store 免费下载）、Node.js 22+（`brew install node@22`）、Apple 开发者账号（你已经有了）。

### 1. 在开发者后台登记 App

[developer.apple.com](https://developer.apple.com/account) → Certificates, Identifiers & Profiles → **Identifiers** → `+` → App IDs：

- Bundle ID 选 Explicit，填 `life.honeytime.tarot`。
- Capabilities 勾选 **Associated Domains**。

在 Membership 页面记下你的 **Team ID**（10 位字母数字）。

### 2. 生成工程并在真机上跑

```bash
git clone https://github.com/axfsz/tarot.git && cd tarot/mobile
APPLE_TEAM_ID=你的TeamID npm run ios
```

- 第一次会安装依赖、生成 iOS 工程、图标和启动图，然后自动打开 Xcode。
- 在 Xcode 顶部选你的 iPhone（数据线连接，手机上需要开启“开发者模式”），点 ▶ 运行。
- 签名用 Xcode 的“自动管理签名”即可。

### 3. 开启 Universal Links

服务器 `.env` 加上 `APP_IOS_TEAM_ID=你的TeamID`，重建 app 容器。打开 `https://honeytime.life/.well-known/apple-app-site-association` 能看到内容就说明生效了。

⚠️ 如果服务器的 nginx 对 `/.well-known/` 有单独的 `location`（例如给 certbot 用的），请确认它会把 `apple-app-site-association` 和 `assetlinks.json` 转发给 app。

### 4. 提交 App Store

1. [App Store Connect](https://appstoreconnect.apple.com) → 我的 App → `+` 新建 App，选择 Bundle ID `life.honeytime.tarot`。
2. Xcode：顶部设备选 **Any iOS Device** → 菜单 **Product → Archive** → 完成后点 **Distribute App → App Store Connect**。
3. 回到 App Store Connect，填写商店资料（文案、隐私问卷、审核备注都在 [`APP_STORE.md`](APP_STORE.md)），选择刚上传的构建版本，提交审核。
4. 上架后把 App 的数字 ID 填进 `.env` 的 `APP_IOS_STORE_ID`。之后 iPhone 用户用 Safari 打开网站时，顶部会出现“打开 App / 获取”横幅。

## iOS 收费规则（重要）

苹果规定 App 内的**数字内容**（AI 解读）只能用苹果内购付款。所以：

- **iOS App 里 AI 解读一律不收费**：后台“收款”页可以选择“免费提供”（默认，仍受每日额度和 AI 预算限制）或“关闭，只在网站提供”。
- 真人咨询属于人对人的服务，可以不走内购。但为稳妥起见，iOS App 里**默认不显示收款方式**，用户会看到“工作室会联系你确认付款方式”。需要显示时，在后台勾选即可。
- 网站和安卓 App 不受影响。

## 更新版本

1. 改 `mobile/package.json` 里的 `"version"`，例如 `0.9.1`。
2. 构建号会自动算成 `901`。商店要求每次上传的构建号都比上次大；同一版本重传时，可以用 `APP_VERSION_CODE=902` 覆盖。
3. 再打包：安卓推送到 GitHub 即可；iOS 在 Mac 上执行 `npm run ios` 后，到 Xcode 里 Archive。

## 文件说明

| 文件 | 作用 |
|---|---|
| `capacitor.config.json` | App ID、名称、加载的网址、User-Agent 标记、启动图设置 |
| `scripts/setup.mjs` | 生成原生工程并打补丁：深链、通知权限、签名、版本号、Info.plist、entitlements |
| `assets/` | 图标和启动图的源文件（由 `@capacitor/assets` 生成各尺寸） |
| `www/offline.html` | 打不开网站时显示的离线页 |

`android/` 和 `ios/` 是生成出来的，默认不提交到 Git；如果以后要在 Xcode / Android Studio 里手动改原生代码，再把它们提交进来。
