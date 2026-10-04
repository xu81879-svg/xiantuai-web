# 鲜图 AI 工作台实现计划

## 目标
在现有空壳项目中建立可运行的 Vue 3 + FastAPI 基础骨架，并实现效果图中的首页工作台布局与核心交互。

## 设计决策
- **Design Movement**：现代 B2B SaaS 工作台，融合生鲜品牌的自然感与轻量玻璃卡片语言。
- **Core Principles**：内容优先、绿色行动色、模块边界清晰、交互反馈明确。
- **Color Philosophy**：用深墨绿承载品牌与标题，用鲜活翡翠绿表达可点击状态，用暖白和浅灰降低长时间操作疲劳。
- **Layout Paradigm**：固定左侧导航 + 顶部品牌栏 + 三列操作工作台；中间是决策区，右侧是结果预览区。
- **Signature Elements**：叶片 logo、绿色编号步骤、商品图片卡与生成结果拼贴。
- **Interaction Philosophy**：选择即预览，上传即识别，生成按钮有明确进度状态，结果支持单张下载。
- **Animation**：卡片 hover 轻微上浮，生成中使用按钮渐变与结果骨架，避免喧宾夺主的动效。
- **Typography System**：系统中文字体优先（PingFang SC / Microsoft YaHei / sans-serif），标题使用 700 字重，辅助说明 12–14px。
- **Brand Essence**：让生鲜商家低成本获得可直接上架的商品视觉素材；关键词：鲜活、可靠、效率。
- **Brand Voice**：直白、有帮助、带一点专业感。示例：“让你的生鲜商品，自动变成能卖货的图片”“选好用途，一键生成整套素材”。
- **Wordmark & Logo**：双叶片线性 mark + “鲜图 AI”文字标识。
- **Signature Brand Color**：#16A765 翡翠绿。

## 结构
- `frontend/src/App.vue`：工作台页面、交互状态与 API 联调。
- `frontend/src/style.css`：全局布局、组件、响应式样式。
- `frontend/public/manus-routes.json`：页面路由清单。
- `backend/app/main.py`：健康检查、商品识别、商品保存、生成任务、素材列表接口。
- `backend/requirements.txt`：FastAPI 与运行依赖。

## 必须完成
1. 首页按照效果图实现顶部导航、左侧菜单、会员卡、三栏工作台和生成结果区。
2. 支持选择商品、修改商品信息、切换图片用途、切换风格。
3. 支持上传商品图片并调用识别接口自动填充商品信息；无后端时保留前端降级体验。
4. 支持一键生成、重新生成、单张下载和全部素材下载。
5. 提供 FastAPI 基础接口，方便后续接入真实 AI Provider 与数据库。
6. 通过前端构建、Python 编译和 HTTP 健康检查验证。
