# Ops Tarot Studio — 78 张塔罗牌图片素材包

## 文件内容

- `cards/major/`：22 张大阿卡纳正面图，按 00–21 编号。
- `cards/wands/`：14 张权杖正面图。
- `cards/cups/`：14 张圣杯正面图。
- `cards/swords/`：14 张宝剑正面图。
- `cards/pentacles/`：14 张星币／钱币正面图。
- `cards/back.png`：唯一共用牌背，所有 78 张牌均引用这一文件。
- `deck.json`：完整牌名、牌义、图片路径、别称、原图裁切坐标与 SHA-256 校验信息。
- `card-image-map.csv`：便于查看或导入的图片对应关系，UTF-8 BOM 编码。
- `preview.jpg`：全套缩略预览，仅用于总览；正式素材均为独立 PNG。
- `verification.json`：文件数量与对应关系校验结果。

## 与 Excel 的对应关系

配套工作簿 `Tarot_78_Cards_With_Images.xlsx` 单独提供。

第一张工作表保留原表 78 行及 9 列文字，在英文牌名后新增 G 列「正面牌图」与 H 列「统一牌背」，原来的象征主题、正位关键词、逆位关键词依次移动至 I、J、K 列。每行均显示其正面与同一张牌背。

所有图片均已嵌入工作簿，离线打开无需解压本素材包。第二张工作表「图片资源索引」保留文件路径及原图出处；只有点击索引中的外部文件链接时，才需要将 tarot-assets 目录与 Excel 文件放在同一目录下。

## tarot 项目使用

将本目录复制到项目的静态目录，例如 `public/assets/tarot/`。部署后，图片基础路径为 `/assets/tarot/`。

示例：

```javascript
const response = await fetch('/assets/tarot/deck.json');
if (!response.ok) throw new Error('Failed to load tarot deck');
const deck = await response.json();
const base = '/assets/tarot/';
const frontUrl = base + deck.cards[0].image;
const backUrl = base + deck.shared_back.image;
```

所有正面均为正位方向。网站需要展示逆位时，可在前端旋转正面图 180 度，不需要另存一套逆位素材。前后图片的容器使用相同尺寸，并设置 `object-fit: contain`，避免拉伸；图片本身保留各自原始裁切尺寸。

这是通用资源清单，并未直接修改或部署你现有的 tarot 项目；如后台已有固定导入格式，需按其字段要求转换。

## 名称映射说明

以原表英文牌名、体系和编号确定对应关系，不仅依赖中文文字。保留原表名称，同时记录图片上印刷的名称：

- 「钱币」对应原表「星币」。
- 「权杖一／圣杯一／宝剑一／钱币一」对应各牌组的「王牌」。
- 大阿卡纳 The Empress 图片上的「女皇」对应原表「皇后」。
- 大阿卡纳 The Emperor 图片上的「国王」对应原表「皇帝」，不与小阿卡纳国王混淆。
- 「倒吊男」对应原表「倒吊人」。
- 小阿卡纳各组的「皇后」对应原表「王后」。

宝剑 1–10 使用较清晰版本；四张宫廷牌使用顶部标有 PAGE、KNIGHT、QUEEN、KING 的另一版本，避开另一张拼图中的错误罗马数字。

## 图片来源与清晰度

全部素材来自本次上传图片，只进行按边界裁切、去除拼图间隔和无损 PNG 保存。没有重新生成、补画或改写牌面文字。正面原始裁切尺寸约为 241–282 像素宽、387–428 像素高；每张准确尺寸和原图位置见 deck.json。

这些是从拼图中提取的原尺寸素材，不是重新制作的印刷级高清单卡。图中符号、道具数量与构图保持原样，本次未作逐项修订。

## 校验

已校验 78 张独立正面、1 张共用牌背，共 79 个 PNG 文件；每个正面文件均对应唯一牌目。Excel 中共有 156 个图片显示位置，内部只保留 79 份唯一图片数据，所有背面显示位置引用相同牌背。
