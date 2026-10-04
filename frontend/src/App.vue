<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

type Usage = { id: string; icon: string; title: string; desc: string }
type StyleItem = { id: string; title: string; image: string; tag?: string }
type Result = { id?: string; title: string; badge: string; image: string; kind: string; product_name?: string; created_at?: string }
type Product = { id?: string; name: string; origin: string; spec: string; tags: string[]; image_url?: string | null; created_at?: string; updated_at?: string }
type Generation = { id: string; status: string; usage: string; style: string; count: number; assets: Result[]; product_id?: string | null; product_name?: string | null; created_at?: string }
type TemplateItem = { id: string; title: string; category: string; description: string; preview_url: string; usage: string; style: string }
type HelpItem = { id: string; category: string; question: string; answer: string }

const API_BASE = '/api'
const staticPreview = import.meta.env.VITE_STATIC_PREVIEW === 'true'
const authenticated = ref(staticPreview)
const authMode = ref<'login' | 'register'>('login')
const authLoading = ref(false)
const authError = ref('')
const showDemoTip = import.meta.env.DEV || staticPreview
const authForm = ref({ email: showDemoTip ? 'demo@xiantu.ai' : '', password: showDemoTip ? 'Demo123456!' : '', display_name: '' })
const authToken = ref(localStorage.getItem('xiantu_token') || '')
const activeNav = ref('首页')
const activeUsage = ref('hero')
const activeStyle = ref('natural')
const isGenerating = ref(false)
const notice = ref('')
const products = ref<Product[]>([])
const libraryAssets = ref<Result[]>([])
const generations = ref<Generation[]>([])
const templates = ref<TemplateItem[]>([])
const helpArticles = ref<HelpItem[]>([])
const listLoading = ref(false)
const listSearch = ref('')
const helpSearch = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const productImage = ref('https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=680&q=85')
const product = ref<Product>({ name: '崂山大樱桃', origin: '山东·青岛崂山', spec: '500g', tags: ['果大', '脆甜', '新鲜', '当季'] })

const usages: Usage[] = [
  { id: 'hero', icon: '▣', title: '电商主图', desc: '白底 / 清晰 / 高转化' },
  { id: 'detail', icon: '▤', title: '详情页卖点', desc: '多角度 / 卖点展示' },
  { id: 'promo', icon: '♧', title: '活动促销', desc: '节日氛围 / 促销文案' },
  { id: 'social', icon: '◒', title: '小红书种草', desc: '生活方式 / 清新自然' },
  { id: 'share', icon: '◉', title: '朋友圈分享', desc: '真实感 / 场景化' },
  { id: 'all', icon: '▱', title: '一键生成整套', desc: '主图+卖点图+场景图' },
]

const styles: StyleItem[] = [
  { id: 'natural', title: '自然生鲜', tag: '推荐', image: 'https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=260&q=80' },
  { id: 'premium', title: '高端精品', image: 'https://images.unsplash.com/photo-1518977676601-b53f82aba655?auto=format&fit=crop&w=260&q=80' },
  { id: 'japanese', title: '清新日系', image: 'https://images.unsplash.com/photo-1592924357228-91a4daadcfea?auto=format&fit=crop&w=260&q=80' },
  { id: 'farm', title: '产地直采', image: 'https://images.unsplash.com/photo-1471943311424-646960669fbc?auto=format&fit=crop&w=260&q=80' },
  { id: 'sale', title: '促销活动', image: 'https://images.unsplash.com/photo-1577003833619-76bbd7f82948?auto=format&fit=crop&w=260&q=80' },
]

const results = ref<Result[]>(staticPreview ? [
  { title: '崂山大樱桃', badge: '电商主图', kind: 'main', image: 'https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=900&q=88' },
  { title: '甜蜜多汁 · 一口爆甜', badge: '详情页卖点', kind: 'detail', image: 'https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=550&q=88' },
  { title: '源自崂山 · 自然成熟', badge: '场景图', kind: 'scene', image: 'https://images.unsplash.com/photo-1471943311424-646960669fbc?auto=format&fit=crop&w=550&q=88' },
  { title: '新鲜大樱桃 · 限时特惠', badge: '促销活动', kind: 'sale', image: 'https://images.unsplash.com/photo-1577003833619-76bbd7f82948?auto=format&fit=crop&w=550&q=88' },
  { title: '把新鲜带回家', badge: '朋友圈分享', kind: 'share', image: 'https://images.unsplash.com/photo-1518977676601-b53f82aba655?auto=format&fit=crop&w=550&q=88' },
] : [])

const generatedCopy = computed(() => results.value.length ? (activeUsage.value === 'all' ? `已生成 ${results.value.length} 张图片` : `已生成 ${results.value.length} 张图片`) : '暂无生成记录')

function authHeaders(extra: HeadersInit = {}): HeadersInit {
  return authToken.value ? { Authorization: `Bearer ${authToken.value}`, ...extra } : extra
}

async function submitAuth() {
  authLoading.value = true
  authError.value = ''
  try {
    const endpoint = authMode.value === 'login' ? '/auth/login' : '/auth/register'
    const response = await fetch(`${API_BASE}${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(authForm.value) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '操作失败')
    authToken.value = data.access_token
    localStorage.setItem('xiantu_token', data.access_token)
    authenticated.value = true
    await loadWorkspaceData()
    notice.value = '登录成功，欢迎回来'
  } catch (error) {
    authError.value = error instanceof Error ? error.message : '操作失败，请稍后重试'
  } finally {
    authLoading.value = false
  }
}

function logout() {
  authToken.value = ''
  localStorage.removeItem('xiantu_token')
  authenticated.value = false
}

onMounted(async () => {
  if (!authToken.value) return
  try {
    const response = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() })
    authenticated.value = response.ok
    if (response.ok) await loadWorkspaceData()
  } catch {
    authenticated.value = false
  }
})

async function loadWorkspaceData() {
  if (staticPreview || !authToken.value) return
  listLoading.value = true
  try {
    const [productsResponse, assetsResponse, generationsResponse, templatesResponse, helpResponse] = await Promise.all([
      fetch(`${API_BASE}/products?q=${encodeURIComponent(listSearch.value)}`, { headers: authHeaders() }),
      fetch(`${API_BASE}/assets?q=${encodeURIComponent(listSearch.value)}`, { headers: authHeaders() }),
      fetch(`${API_BASE}/generations`, { headers: authHeaders() }),
      fetch(`${API_BASE}/templates`, { headers: authHeaders() }),
      fetch(`${API_BASE}/help?q=${encodeURIComponent(helpSearch.value)}`, { headers: authHeaders() }),
    ])
    if (productsResponse.ok) products.value = (await productsResponse.json()).items ?? []
    if (assetsResponse.ok) libraryAssets.value = (await assetsResponse.json()).items ?? []
    if (generationsResponse.ok) {
      generations.value = (await generationsResponse.json()).items ?? []
      if (!staticPreview && !results.value.length && generations.value[0]?.assets?.length) results.value = generations.value[0].assets
    }
    if (templatesResponse.ok) templates.value = (await templatesResponse.json()).items ?? []
    if (helpResponse.ok) helpArticles.value = (await helpResponse.json()).items ?? []
  } finally {
    listLoading.value = false
  }
}

watch(activeNav, async (value) => {
  if (value === '我的商品' || value === '我的产品' || value === '素材库' || value === '生成记录' || value === '模板中心' || value === '帮助中心') await loadWorkspaceData()
})

async function useTemplate(template: TemplateItem) {
  activeUsage.value = template.usage
  activeStyle.value = template.style
  activeNav.value = '首页'
  notice.value = `已应用模板「${template.title}」`
}

async function saveProduct() {
  if (staticPreview) { notice.value = '静态预览模式：商品会保存到真实商品库'; return }
  const response = await fetch(product.value.id ? `${API_BASE}/products/${product.value.id}` : `${API_BASE}/products`, {
    method: product.value.id ? 'PUT' : 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(product.value),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || '商品保存失败')
  product.value = data
  await loadWorkspaceData()
  notice.value = '商品信息已保存'
}

async function selectProduct(item: Product) {
  product.value = { ...item, tags: item.tags ?? [] }
  productImage.value = item.image_url || productImage.value
  activeNav.value = '首页'
  notice.value = `已载入商品「${item.name}」`
}

async function removeProduct(item: Product) {
  if (!item.id || !confirm(`确定删除「${item.name}」吗？`)) return
  const response = await fetch(`${API_BASE}/products/${item.id}`, { method: 'DELETE', headers: authHeaders() })
  if (!response.ok) { notice.value = '商品删除失败'; return }
  await loadWorkspaceData()
  notice.value = '商品已删除'
}

function toggleTag(tag: string) {
  const tags = product.value.tags
  product.value.tags = tags.includes(tag) ? tags.filter((item) => item !== tag) : [...tags, tag]
}

function triggerUpload() {
  fileInput.value?.click()
}

function handleFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  productImage.value = URL.createObjectURL(file)
  notice.value = '图片已上传，正在识别商品信息…'
  recognize(file)
}

async function recognize(file: File) {
  try {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${API_BASE}/products/recognize`, { method: 'POST', headers: authHeaders(), body: form })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || '图片识别失败')
    }
    const data = await response.json()
    product.value = { ...product.value, ...data, tags: data.tags ?? product.value.tags }
    notice.value = 'AI 已识别商品信息，你可以继续编辑'
  } catch (error) {
    notice.value = staticPreview ? '静态预览模式：这里会连接真实 AI 识别服务' : (error instanceof Error ? error.message : '图片识别失败，请稍后重试')
  }
}

async function generate() {
  if (isGenerating.value) return
  isGenerating.value = true
  notice.value = 'AI 正在根据商品信息生成整套素材…'
  try {
    await saveProduct()
    const response = await fetch(`${API_BASE}/generations`, {
      method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ product: product.value, usage: activeUsage.value, style: activeStyle.value }),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || '生成失败，请稍后重试')
    }
    const data = await response.json()
    if (Array.isArray(data.assets) && data.assets.length) results.value = data.assets
    await loadWorkspaceData()
    notice.value = '生成完成，素材已准备好'
  } catch (error) {
    notice.value = staticPreview ? '静态预览模式：这里会连接真实 AI 生图服务' : (error instanceof Error ? error.message : '生成失败，请稍后重试')
  } finally {
    isGenerating.value = false
  }
}

function downloadAsset(asset: Result) {
  const link = document.createElement('a')
  link.href = asset.image
  link.download = `${asset.title}.jpg`
  link.target = '_blank'
  link.click()
  notice.value = `正在下载「${asset.title}」`
}

function downloadAll() {
  results.value.forEach((asset, index) => window.setTimeout(() => downloadAsset(asset), index * 180))
  notice.value = '正在下载全部素材'
}
</script>

<template>
  <div>
    <div v-if="!authenticated" class="auth-screen">
      <div class="auth-card">
        <div class="auth-brand"><div class="brand-mark" aria-hidden="true"><span></span><i></i></div><div><strong>鲜图 <em>AI</em></strong><small>生鲜商品 AI 视觉助手</small></div></div>
        <h1>{{ authMode === 'login' ? '欢迎回到鲜图 AI' : '创建你的鲜图账户' }}</h1>
        <p class="auth-subtitle">面向亚洲生鲜商家的商品视觉工作台</p>
        <label v-if="authMode === 'register'" class="auth-input"><span>商家名称</span><input v-model="authForm.display_name" placeholder="例如：青岛鲜果铺" /></label>
        <label class="auth-input"><span>邮箱</span><input v-model="authForm.email" type="email" placeholder="name@company.com" /></label>
        <label class="auth-input"><span>密码</span><input v-model="authForm.password" type="password" placeholder="至少 8 位字符" @keyup.enter="submitAuth" /></label>
        <p v-if="authError" class="auth-error">{{ authError }}</p>
        <button class="auth-submit" :disabled="authLoading" @click="submitAuth">{{ authLoading ? '处理中…' : (authMode === 'login' ? '登录工作台' : '注册并开始使用') }}</button>
        <button class="auth-switch" @click="authMode = authMode === 'login' ? 'register' : 'login'; authError = ''">{{ authMode === 'login' ? '还没有账户？立即注册' : '已有账户？返回登录' }}</button>
        <small v-if="showDemoTip" class="demo-tip">开发演示账号：demo@xiantu.ai / Demo123456!</small>
      </div>
    </div>
    <div v-else class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true"><span></span><i></i></div>
        <div><strong>鲜图 <em>AI</em></strong><small>生鲜商品 AI 视觉助手</small></div>
      </div>
      <nav class="top-nav">
        <button v-for="item in ['首页', '我的产品', '素材库', '模板中心']" :key="item" :class="{ active: activeNav === item }" @click="activeNav = item">{{ item }}</button>
      </nav>
      <button class="account" @click="logout"><span class="avatar">●</span>商家用户<span class="chevron">⌄</span></button>
    </header>

    <div class="body-layout">
      <aside class="sidebar">
        <div class="side-menu">
          <button v-for="item in [{icon:'⌂',label:'首页'}, {icon:'▤',label:'我的商品'}, {icon:'▧',label:'素材库'}, {icon:'▢',label:'生成记录'}, {icon:'▣',label:'模板中心'}, {icon:'?',label:'帮助中心'}]" :key="item.label" :class="{ selected: activeNav === item.label || (activeNav === '首页' && item.label === '首页') }" @click="activeNav = item.label; notice = ''"><span>{{ item.icon }}</span>{{ item.label }}</button>
        </div>
        <div class="upgrade-card">
          <div class="crown">♛</div><strong>会员升级</strong>
          <p>解锁更多高级功能<br />批量生成、详情页、视频等</p>
          <button @click="notice = '会员升级功能即将上线'">立即升级</button>
        </div>
        <button class="brand-card" @click="notice = '鲜图 AI：让生鲜商家更轻松地卖货'"><img src="https://images.unsplash.com/photo-1542838132-92c53300491e?auto=format&fit=crop&w=180&q=80" alt="生鲜商品" /><span><b>鲜图 AI</b><small>让生鲜商家<br />更轻松地卖货</small></span></button>
        <div class="fresh-note"><span>好 生 鲜</span><b>需要好图片</b><div class="scribble">↗</div><div class="scenery"></div></div>
      </aside>

      <main class="main-content">
        <section v-if="activeNav === '我的商品' || activeNav === '我的产品'" class="data-page">
          <div class="data-page-header"><div><span class="eyebrow">PRODUCTS</span><h1>我的商品</h1><p>管理已保存的生鲜商品，生成时会自动使用最新信息。</p></div><button class="primary-small" @click="activeNav = '首页'">＋ 新建商品</button></div>
          <div class="data-toolbar"><input v-model="listSearch" placeholder="搜索商品名称或产地" @keyup.enter="loadWorkspaceData" /><button @click="loadWorkspaceData">搜索</button><span v-if="listLoading">正在同步…</span><span v-else>共 {{ products.length }} 个商品</span></div>
          <div v-if="products.length" class="product-list"><article v-for="item in products" :key="item.id" class="product-list-card"><img :src="item.image_url || productImage" :alt="item.name" /><div class="product-list-copy"><h3>{{ item.name }}</h3><p>{{ item.origin }} · {{ item.spec }}</p><div class="list-tags"><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div><small>更新于 {{ item.updated_at ? new Date(item.updated_at).toLocaleDateString('zh-CN') : '刚刚' }}</small></div><div class="list-actions"><button @click="selectProduct(item)">编辑并使用</button><button class="danger-link" @click="removeProduct(item)">删除</button></div></article></div>
          <div v-else class="empty-state"><div>▧</div><h3>还没有保存的商品</h3><p>回到首页编辑商品信息，点击生成时会自动保存。</p><button class="primary-small" @click="activeNav = '首页'">开始添加商品</button></div>
        </section>
        <section v-else-if="activeNav === '素材库'" class="data-page">
          <div class="data-page-header"><div><span class="eyebrow">ASSET LIBRARY</span><h1>素材库</h1><p>集中查看真实生成记录中的商品素材，可直接下载单张成品。</p></div><button class="primary-small" @click="activeNav = '首页'">去生成素材</button></div>
          <div class="data-toolbar"><input v-model="listSearch" placeholder="搜索素材标题或商品名称" @keyup.enter="loadWorkspaceData" /><button @click="loadWorkspaceData">搜索</button><span v-if="listLoading">正在同步…</span><span v-else>共 {{ libraryAssets.length }} 张素材</span></div>
          <div v-if="libraryAssets.length" class="library-grid"><article v-for="asset in libraryAssets" :key="asset.id || asset.title" class="library-card"><div class="library-image"><img :src="asset.image" :alt="asset.title" /><span>{{ asset.badge }}</span><button @click="downloadAsset(asset)">↓</button></div><div><h3>{{ asset.title }}</h3><p>{{ asset.product_name || '未命名商品' }} · {{ asset.created_at ? new Date(asset.created_at).toLocaleDateString('zh-CN') : '刚刚' }}</p></div></article></div>
          <div v-else class="empty-state"><div>✦</div><h3>素材库还是空的</h3><p>完成一次生成后，全部成品会自动归档到这里。</p><button class="primary-small" @click="activeNav = '首页'">生成第一套素材</button></div>
        </section>
        <section v-else-if="activeNav === '生成记录'" class="data-page">
          <div class="data-page-header"><div><span class="eyebrow">GENERATION HISTORY</span><h1>生成记录</h1><p>每次生成的用途、风格和素材数量都会保存在账户中。</p></div><button class="primary-small" @click="activeNav = '首页'">继续生成</button></div>
          <div v-if="generations.length" class="history-list"><article v-for="item in generations" :key="item.id" class="history-card"><div class="history-thumb"><img v-if="item.assets?.[0]?.image" :src="item.assets[0].image" alt="生成记录" /><span v-else>✦</span></div><div class="history-copy"><h3>{{ item.product_name || '未命名商品' }}</h3><p>{{ item.usage }} · {{ item.style }} · {{ item.count }} 张素材</p><small>{{ item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '刚刚' }}</small></div><button class="list-actions-button" @click="results = item.assets; activeNav = '首页'">查看结果</button></article></div>
          <div v-else class="empty-state"><div>◷</div><h3>还没有生成记录</h3><p>完成一次千问生成后，记录会自动出现在这里。</p><button class="primary-small" @click="activeNav = '首页'">开始生成</button></div>
          <button v-if="generations.length" class="secondary-refresh" @click="loadWorkspaceData">刷新数据</button>
        </section>
        <section v-else-if="activeNav === '模板中心'" class="data-page">
          <div class="data-page-header"><div><span class="eyebrow">TEMPLATE CENTER</span><h1>模板中心</h1><p>从真实模板库选择用途和风格，应用后回到首页生成。</p></div><span class="data-count">共 {{ templates.length }} 个模板</span></div>
          <div v-if="templates.length" class="template-grid"><article v-for="template in templates" :key="template.id" class="template-card"><div class="template-preview"><img :src="template.preview_url" :alt="template.title" /><span>{{ template.category }}</span></div><div class="template-copy"><h3>{{ template.title }}</h3><p>{{ template.description }}</p><button class="primary-small" @click="useTemplate(template)">应用模板</button></div></article></div>
          <div v-else class="empty-state"><div>▱</div><h3>模板库为空</h3><p>请先完成数据库迁移，或联系管理员添加模板。</p></div>
        </section>
        <section v-else-if="activeNav === '帮助中心'" class="data-page">
          <div class="data-page-header"><div><span class="eyebrow">HELP CENTER</span><h1>帮助中心</h1><p>从真实帮助文章中搜索商品识别、千问生成和账户数据问题。</p></div></div>
          <div class="data-toolbar"><input v-model="helpSearch" placeholder="搜索问题或关键词" @keyup.enter="loadWorkspaceData" /><button @click="loadWorkspaceData">搜索</button><span>共 {{ helpArticles.length }} 篇文章</span></div>
          <div v-if="helpArticles.length" class="help-list"><article v-for="article in helpArticles" :key="article.id" class="help-card"><span>{{ article.category }}</span><h3>{{ article.question }}</h3><p>{{ article.answer }}</p></article></div>
          <div v-else class="empty-state"><div>?</div><h3>没有匹配的帮助文章</h3><p>尝试更换关键词。</p></div>
        </section>
        <template v-else>
        <section class="hero-banner">
          <div class="hero-copy"><h1>让你的生鲜商品<br /><strong>自动变成能卖货的图片</strong></h1><p>上传商品　·　AI智能识别　·　一键生成整套素材</p><div class="hero-points"><span>⚡ <b>30秒出图</b><small>高效省时</small></span><span>✣ <b>专业构图</b><small>提升转化</small></span><span>▦ <b>多场景模板</b><small>电商/社媒/活动</small></span><span>✓ <b>真实生鲜感</b><small>更具信任</small></span></div></div>
          <div class="hero-fruit"></div><div class="hero-slogan">新鲜 × 美味 × 好卖</div>
        </section>

        <div class="workspace-grid">
          <section class="panel product-panel">
            <div class="step-title"><span>1</span><div><b>选择商品</b><small>上传商品图片或从素材库选择</small></div></div>
            <div class="product-card"><div class="product-thumb"><img :src="productImage" alt="商品图片" /><button class="remove">×</button></div><div class="product-summary"><b>{{ product.name }}</b><span>{{ product.spec }} / 精品装</span><button class="outline-btn" @click="triggerUpload">↥　更换图片</button></div></div>
            <input ref="fileInput" type="file" accept="image/*" hidden @change="handleFile" />
            <div class="section-label">商品信息 <small>（AI自动识别，可编辑）</small></div>
            <label class="field"><span>商品名称</span><input v-model="product.name" maxlength="30" /><i>{{ product.name.length }}/30</i></label>
            <div class="field tag-field"><span>卖点标签</span><div class="tags"><button v-for="tag in ['果大','脆甜','新鲜','当季']" :key="tag" :class="{ chosen: product.tags.includes(tag) }" @click="toggleTag(tag)">{{ tag }}</button><button class="plus" @click="product.tags.push('精选')">＋</button></div></div>
            <label class="field"><span>产地</span><input v-model="product.origin" /></label>
            <label class="field"><span>规格</span><input v-model="product.spec" /></label>
            <div class="ai-hint">♧　AI 已智能识别商品信息，您也可以手动修改<br /><small>让图片更符合你的需求。</small></div>
            <button class="save-product-btn" @click="saveProduct">保存商品信息</button>
          </section>

          <section class="panel control-panel">
            <div class="step-title"><span>2</span><div><b>选择图片用途</b><small>AI 会根据用途自动匹配最佳风格与构图</small></div></div>
            <div class="usage-grid"><button v-for="usage in usages" :key="usage.id" class="usage-card" :class="{ chosen: activeUsage === usage.id }" @click="activeUsage = usage.id"><span class="usage-icon">{{ usage.icon }}</span><b>{{ usage.title }}</b><small>{{ usage.desc }}</small><em v-if="activeUsage === usage.id">✓</em></button></div>
            <div class="step-title style-step"><span>3</span><div><b>选择风格</b><small>AI 会根据商品自动推荐合适的风格</small></div></div>
            <div class="style-scroll"><button v-for="style in styles" :key="style.id" class="style-card" :class="{ chosen: activeStyle === style.id }" @click="activeStyle = style.id"><div><img :src="style.image" alt="" /><em v-if="style.tag">{{ style.tag }}</em></div><b>{{ style.title }}</b></button></div>
            <button class="generate-btn" :class="{ loading: isGenerating }" @click="generate"><span>{{ isGenerating ? '✦ 正在生成，请稍候…' : '✦ 一键生成整套图片　→' }}</span></button><p class="time-tip">预计耗时 30-60 秒</p>
          </section>

          <section class="panel result-panel">
            <div class="result-header"><div class="step-title compact"><span class="sparkle">✦</span><div><b>生成结果</b><small>{{ generatedCopy }}</small></div></div><button class="refresh" @click="generate">⟳　重新生成</button></div>
            <div v-if="results.length" class="result-grid"><article v-for="asset in results" :key="asset.id || asset.title" class="result-card" :class="asset.kind"><img :src="asset.image" alt="生成结果" /><div class="result-overlay"><span>{{ asset.badge }}</span><button @click="downloadAsset(asset)">↓</button></div><strong v-if="asset.kind === 'main'">{{ product.name }}</strong><small v-if="asset.kind === 'main'">{{ product.tags.join(' · ') }}</small></article></div>
            <div v-else class="result-empty"><span>✦</span><b>还没有生成结果</b><small>选择用途和风格后，点击一键生成整套图片</small></div>
            <div class="result-footer"><span>●　已为你生成 {{ results.length }} 张高质量图片，包含多种使用场景</span><button @click="downloadAll">⇩　下载整套素材</button></div>
          </section>
        </div>
        </template>
      </main>
    </div>
    <div v-if="notice" class="toast">{{ notice }}</div>
    </div>
  </div>
</template>
