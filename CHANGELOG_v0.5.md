# v0.5.0 优化说明（基于 v0.4.1）

业务逻辑、数据库结构与 API 行为保持兼容，旧数据无需迁移。直接替换源码后 `docker compose up -d --build` 即可。

## 一、性能 / 加载速度

| 项目 | v0.4.1 | v0.5.0 |
|---|---|---|
| 78 张牌面＋牌背体积 | 15.1 MB（PNG） | 2.2 MB（WebP，画质 84，约 −85%） |
| 首页主视觉 3 张牌图 | ≈640 KB | ≈100 KB |
| 首页首屏 JS+CSS+数据传输 | ≈150 KB（未压缩） | ≈40 KB（gzip） |
| `/api/bootstrap` | 77 KB，每次登录/保存都重下牌库 | 0.7 KB；牌库拆到 `/api/catalog`，按内容哈希永久缓存 |
| 静态资源缓存 | `no-cache`，每次都要校验 | 带版本号的 JS/CSS/牌库 1 年 `immutable`；牌面 30 天 |

- 新增 `static/tarot/cards/**/*.webp`；原 PNG 保留作溯源校验（`deck.json` SHA-256 不变），浏览器只加载 WebP。旧的已保存牌阵也会自动改用 WebP。
- JS/CSS 版本号改为文件内容哈希，自动失效缓存，不用再手动改 `?v=`。
- 应用内置 gzip（反代未压缩时生效），并更新 `nginx.conf.example`：HTTP/2、gzip、TLS 会话缓存。
- 首页主图 `preload` + `fetchpriority`，牌库 `preload`，图片加 `width/height` 防止布局抖动、`decoding=async`。
- AI 生成过程中轮询只刷新报告文字，不再每 1.3 秒重绘整页（不闪、不丢滚动位置）。
- 后台任务线程每秒扫描改为先用 SQL `LIKE` 预筛“生成中”记录，历史越多节省越明显。
- Docker 镜像排除未使用的 1.3 MB `preview.jpg`。

## 二、SEO 与分享

- 每页独立 `title` / `description` / `canonical`，中英文 `hreflang`（`?lang=en`）。
- 新增可被收录的真实路径：`/ai`、`/human`、`/learn`、`/contact`、`/terms`（原先只有 `#hash`，搜索引擎视为同一页）。
- 服务端预渲染：首页主视觉、20 种牌阵、**78 张牌义全文**直接写在 HTML 中，无 JS 的爬虫也能读到；JS 加载后无缝接管。
- Open Graph / Twitter 卡片 + 1200×630 分享图 `static/og-image.jpg`。
- JSON-LD 结构化数据（Organization / WebSite / WebPage）。
- `robots.txt`（屏蔽 `/api/`、`/admin`、`/setup`）、`sitemap.xml`（含 hreflang）、`manifest.webmanifest`、PNG 图标与 apple-touch-icon。
- 后台、安装页与 404 页 `noindex`；未知路径返回真正的 404 状态码。
- 新增环境变量 `SITE_URL`（默认 `https://tarot.opsglobalonline.com`），用于 canonical 与 sitemap，不信任 Host 头。

## 三、界面与移动端

- 修复首页三张主视觉牌：左侧“月亮”原本叠在中间未展开（CSS `:first-of-type` 误命中装饰圆环）。
- 手机端导航改为汉堡菜单（原导航换行占掉约半屏），支持 Esc 关闭、点外部关闭。
- 手机端首页显示缩小版主视觉；按钮、输入框触控高度 ≥44px；适配刘海屏安全区域。
- 手机端牌阵默认列表视图（原默认宽布局会被截断需横向滚动）。
- 切换页面自动回到顶部并聚焦主内容；每页更新标签页标题；当前导航项高亮（`aria-current`）。
- 新抽出的牌带翻牌动效（尊重“减少动态效果”系统设置）。
- 键盘可访问：“跳到主要内容”链接、牌堆焦点样式；Toast 连续提示不再互相提前关闭。
- 登录/注册/预约表单加 `autocomplete`，密码管理器与手机自动填充可用。
- 网络错误、服务器 502 等返回友好中英文提示，不再出现 JSON 解析错误；启动失败显示可重试页面。
- 浏览器禁用本地存储（隐私模式）时不再报错。
- 页脚显示版权年份。

## 四、代码质量与安全

- 新增安全头：`Permissions-Policy`、`Cross-Origin-Opener-Policy`、HTTPS 下 `Strict-Transport-Security`；CSP 补 `object-src 'none'` 等；Referrer 改为 `strict-origin-when-cross-origin`。
- 登录对不存在的用户名也做一次哈希比较，避免通过响应时间枚举用户名。
- “我的记录”、后台预约/订单/审计日志统一按时间倒序：PostgreSQL 不保证行顺序，原来依赖插入顺序在生产库上会乱序。
- 清理函数内重复 `import`；Gunicorn 输出访问日志。
- 新增 10 项测试（`tests/test_web_v05.py`）：SEO 标签、英文页、404/noindex、robots/sitemap/manifest、牌库缓存、WebP 资源、gzip、安全头、记录排序、登录错误一致性。**全部 120 项测试通过。**

## 部署提示

1. 如使用自定义域名以外的地址，在 `.env` 设置 `SITE_URL=https://你的域名`。
2. 按新的 `nginx.conf.example` 更新 Nginx（可选但推荐：HTTP/2 + gzip），`nginx -t && systemctl reload nginx`。
3. 上线后在 Google Search Console / 百度站长提交 `https://tarot.opsglobalonline.com/sitemap.xml`。
4. 用 Facebook Sharing Debugger 等工具检查分享卡片；微信内分享卡片需公众号 JS-SDK，另行配置。
