<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

declare global {
  interface Window { paypal?: any }
}

type Usage = { id: string; icon: string; title: string; desc: string }
type StyleItem = { id: string; title: string; image: string; tag?: string }
type Result = { id?: string; title: string; badge: string; image: string; kind: string; product_name?: string; product_origin?: string; product_spec?: string; product_tags?: string[]; created_at?: string }
type Product = { id?: string; name: string; origin: string; spec: string; tags: string[]; image_url?: string | null; recognition_confidence?: number; recognition_evidence?: string; created_at?: string; updated_at?: string }
type Generation = { id: string; status: string; usage: string; style: string; count: number; assets: Result[]; product_id?: string | null; product_name?: string | null; created_at?: string }
type TemplateItem = { id: string; title: string; category: string; description: string; preview_url: string; usage: string; style: string }
type HelpItem = { id: string; category: string; question: string; answer: string }
type CreditPlan = { code: string; name: string; description: string; credits: number; amount: string; currency: string }
type PosterTheme = { id: string; title: string; desc: string; kicker: string; accent: string; panel: string; tag: string; meta: string }

const API_BASE = '/api'
const staticPreview = import.meta.env.VITE_STATIC_PREVIEW === 'true'
const authenticated = ref(staticPreview)
const authMode = ref<'login' | 'register'>('login')
const authLoading = ref(false)
const authError = ref('')
const demoEmail = import.meta.env.VITE_DEMO_EMAIL || ''
const demoPassword = import.meta.env.VITE_DEMO_PASSWORD || ''
const showDemoTip = (import.meta.env.DEV || staticPreview) && Boolean(demoEmail && demoPassword)
const authForm = ref({ email: showDemoTip ? demoEmail : '', password: showDemoTip ? demoPassword : '', display_name: '' })
const authToken = ref(localStorage.getItem('xiantu_token') || '')
const activeNav = ref('首页')
const activeUsage = ref('hero')
const activeStyle = ref('natural')
const activeTone = ref('fresh')
const activeComposition = ref('center')
const activeBackground = ref('clean')
const activePlatform = ref('taobao')
const activePosterTheme = ref('fresh')
const posterCopy = ref({ kicker: '', title: '', subtitle: '', tags: '' })
const isGenerating = ref(false)
const isRecognizing = ref(false)
const notice = ref('')
const products = ref<Product[]>([])
const libraryAssets = ref<Result[]>([])
const generations = ref<Generation[]>([])
const templates = ref<TemplateItem[]>([])
const helpArticles = ref<HelpItem[]>([])
const creditPlans = ref<CreditPlan[]>([])
const creditBalance = ref(staticPreview ? 10 : 0)
const showBilling = ref(false)
const billingLoading = ref(false)
const paypalClientId = ref('')
const paypalCurrency = ref('USD')
const paypalOrderIds = new Map<string, string>()
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

const posterThemes: PosterTheme[] = [
  { id: 'fresh', title: '清新上新', desc: '绿色自然', kicker: '今日鲜选', accent: '#42d18a', panel: '#062b1a', tag: '#15965a', meta: '#e6f8ec' },
  { id: 'premium', title: '精品质感', desc: '黑金高级', kicker: '甄选好物', accent: '#d8b36a', panel: '#1d1710', tag: '#8b6730', meta: '#f6ecd7' },
  { id: 'sale', title: '活动转化', desc: '红橙醒目', kicker: '人气推荐', accent: '#ffb547', panel: '#351118', tag: '#bd3b37', meta: '#ffe5d7' },
  { id: 'minimal', title: '极简留白', desc: '黑白克制', kicker: '商品主视觉', accent: '#ffffff', panel: '#111318', tag: '#3d4652', meta: '#e8edf2' },
  { id: 'warm', title: '温暖生活', desc: '陶土暖调', kicker: '把新鲜带回家', accent: '#f1a36d', panel: '#321d18', tag: '#a95e42', meta: '#ffe9dc' },
]
const currentPosterTheme = computed(() => posterThemes.find((theme) => theme.id === activePosterTheme.value) || posterThemes[0])

const tones = [{ id: 'fresh', title: '清新自然' }, { id: 'premium', title: '高级质感' }, { id: 'warm', title: '温暖生活' }, { id: 'sale', title: '促销醒目' }]
const compositions = [{ id: 'center', title: '主体居中' }, { id: 'rule-of-thirds', title: '三分构图' }, { id: 'close-up', title: '近景特写' }, { id: 'flat-lay', title: '俯拍平铺' }]
const backgrounds = [{ id: 'clean', title: '简洁留白' }, { id: 'farm', title: '产地场景' }, { id: 'table', title: '餐桌生活' }, { id: 'festival', title: '节日氛围' }]
const platforms = [{ id: 'taobao', title: '淘宝 / 京东' }, { id: 'xiaohongshu', title: '小红书' }, { id: 'wechat', title: '朋友圈' }, { id: 'douyin', title: '抖音电商' }]

const results = ref<Result[]>(staticPreview ? [
  { title: '崂山大樱桃', badge: '电商主图', kind: 'main', image: 'https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=900&q=88' },
  { title: '甜蜜多汁 · 一口爆甜', badge: '详情页卖点', kind: 'detail', image: 'https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=550&q=88' },
  { title: '源自崂山 · 自然成熟', badge: '场景图', kind: 'scene', image: 'https://images.unsplash.com/photo-1471943311424-646960669fbc?auto=format&fit=crop&w=550&q=88' },
  { title: '新鲜大樱桃 · 限时特惠', badge: '促销活动', kind: 'sale', image: 'https://images.unsplash.com/photo-1577003833619-76bbd7f82948?auto=format&fit=crop&w=550&q=88' },
  { title: '把新鲜带回家', badge: '朋友圈分享', kind: 'share', image: 'https://images.unsplash.com/photo-1518977676601-b53f82aba655?auto=format&fit=crop&w=550&q=88' },
] : [])

const previewPlans: CreditPlan[] = [
  { code: 'starter', name: '尝鲜包', description: '适合第一次体验，生成 20 张素材', credits: 20, amount: '5.00', currency: 'USD' },
  { code: 'pro', name: '专业包', description: '适合日常经营，生成 100 张素材', credits: 100, amount: '19.00', currency: 'USD' },
  { code: 'business', name: '商家包', description: '适合批量营销，生成 300 张素材', credits: 300, amount: '49.00', currency: 'USD' },
]

if (staticPreview) {
  products.value = [{ id: 'preview-product-1', name: '崂山大樱桃', origin: '山东·青岛崂山', spec: '500g', tags: ['果大', '脆甜', '新鲜', '当季'], image_url: productImage.value }]
  libraryAssets.value = results.value.map((asset, index) => ({ ...asset, id: `preview-asset-${index + 1}`, product_name: '崂山大樱桃' }))
  generations.value = [{ id: 'preview-generation-1', status: 'completed', usage: 'hero', style: 'natural', count: results.value.length, assets: results.value, product_id: 'preview-product-1', product_name: '崂山大樱桃', created_at: new Date().toISOString() }]
  templates.value = [
    { id: 'preview-template-1', title: '自然生鲜主图', category: '电商主图', description: '突出新鲜质感与商品主体，适合商品首图。', preview_url: styles[0].image, usage: 'hero', style: 'natural' },
    { id: 'preview-template-2', title: '精品详情卖点', category: '详情页', description: '适合展示规格、口感与品质卖点。', preview_url: styles[1].image, usage: 'detail', style: 'premium' },
    { id: 'preview-template-3', title: '产地直采场景', category: '场景图', description: '用自然环境强化产地与真实感。', preview_url: styles[3].image, usage: 'social', style: 'farm' },
  ]
  helpArticles.value = [
    { id: 'preview-help-1', category: '快速开始', question: '如何生成第一套商品素材？', answer: '确认商品信息后选择用途和风格，点击一键生成整套图片即可。' },
    { id: 'preview-help-2', category: '支付额度', question: '额度包如何购买？', answer: '点击左侧购买额度，在弹窗中选择一次性额度包。正式环境将通过 PayPal 完成支付。' },
    { id: 'preview-help-3', category: 'AI 服务', question: '千问生成失败怎么办？', answer: '检查 Railway Variables 中的 QWEN_API_KEY 和模型配置，并重试一次。' },
  ]
}

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
    await loadBilling()
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
    if (response.ok) {
      await loadWorkspaceData()
      await loadBilling()
      const params = new URLSearchParams(window.location.search)
      const localOrderId = params.get('paypal_order_id')
      const paypalOrderId = params.get('token') || localOrderId
      if (localOrderId && paypalOrderId) await capturePayPalOrder(localOrderId, paypalOrderId)
    }
  } catch {
    authenticated.value = false
  }
})

async function loadBilling() {
  if (staticPreview || !authToken.value) return
  const response = await fetch(`${API_BASE}/billing/plans`, { headers: authHeaders() })
  if (!response.ok) return
  const data = await response.json()
  creditPlans.value = data.items ?? []
  creditBalance.value = data.credit_balance ?? 0
}

async function openBilling() {
  if (staticPreview) {
    creditPlans.value = previewPlans
    showBilling.value = true
    notice.value = '预览模式：可模拟购买额度包，正式环境将切换为 PayPal 支付'
    return
  }
  await loadBilling()
  showBilling.value = true
  await nextTick()
  await renderPaypalButtons()
}

async function loadPaypalSdk() {
  const configResponse = await fetch(`${API_BASE}/billing/paypal/config`, { headers: authHeaders() })
  if (!configResponse.ok) return false
  const config = await configResponse.json()
  paypalClientId.value = config.client_id || ''
  paypalCurrency.value = config.currency || 'USD'
  if (!paypalClientId.value || !config.enabled) return false
  if (window.paypal) return true
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(paypalClientId.value)}&currency=${encodeURIComponent(paypalCurrency.value)}&intent=capture&components=buttons`
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('PayPal SDK 加载失败'))
    document.head.appendChild(script)
  })
  return Boolean(window.paypal)
}

async function renderPaypalButtons() {
  try {
    if (!(await loadPaypalSdk()) || !window.paypal) return
    for (const plan of creditPlans.value) {
      const host = document.getElementById(`paypal-button-${plan.code}`)
      if (!host || host.dataset.rendered === 'true') continue
      host.dataset.rendered = 'true'
      await window.paypal.Buttons({
        style: { layout: 'vertical', shape: 'rect', label: 'paypal', height: 38 },
        createOrder: async () => {
          const response = await fetch(`${API_BASE}/billing/paypal/orders`, { method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ plan_code: plan.code }) })
          const data = await response.json()
          if (!response.ok || !data.paypal_order_id) throw new Error(data.detail || 'PayPal 订单创建失败')
          paypalOrderIds.set(plan.code, data.order.id)
          return data.paypal_order_id
        },
        onApprove: async (data: { orderID: string }) => {
          const localOrderId = paypalOrderIds.get(plan.code)
          if (localOrderId) await capturePayPalOrder(localOrderId, data.orderID)
        },
        onCancel: () => { notice.value = '你已取消 PayPal 支付' },
        onError: (error: unknown) => { notice.value = error instanceof Error ? error.message : 'PayPal 支付失败，请稍后重试' },
      }).render(`#paypal-button-${plan.code}`)
    }
  } catch (error) {
    notice.value = error instanceof Error ? error.message : 'PayPal 按钮加载失败'
  }
}

async function purchasePlan(plan: CreditPlan) {
  billingLoading.value = true
  try {
    if (staticPreview) {
      await new Promise((resolve) => window.setTimeout(resolve, 350))
      creditBalance.value += plan.credits
      showBilling.value = false
      notice.value = `模拟购买成功，已增加 ${plan.credits} 次额度`
      return
    }
    const response = await fetch(`${API_BASE}/billing/paypal/orders`, { method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ plan_code: plan.code }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'PayPal 订单创建失败')
    if (data.approval_url) {
      window.location.href = data.approval_url
      return
    }
    creditBalance.value = data.credit_balance ?? creditBalance.value
    showBilling.value = false
    notice.value = `额度包已到账，可生成 ${creditBalance.value} 次素材`
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '购买失败，请稍后重试'
  } finally {
    billingLoading.value = false
  }
}

async function capturePayPalOrder(localOrderId: string, paypalOrderId: string) {
  const response = await fetch(`${API_BASE}/billing/paypal/orders/${localOrderId}/capture`, { method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ paypal_order_id: paypalOrderId }) })
  const data = await response.json().catch(() => ({}))
  if (response.ok) {
    creditBalance.value = data.credit_balance ?? creditBalance.value
    showBilling.value = false
    notice.value = `PayPal 支付成功，当前剩余 ${creditBalance.value} 次额度`
    window.history.replaceState({}, '', window.location.pathname)
  } else {
    notice.value = data.detail || 'PayPal 支付尚未完成'
  }
}

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
  if (staticPreview) {
    const previewProduct = { ...product.value, id: product.value.id || 'preview-product-1', image_url: productImage.value }
    product.value = previewProduct
    products.value = [previewProduct]
    notice.value = '预览模式：商品信息已保存在当前页面'
    return
  }
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
  if (isRecognizing.value) return
  fileInput.value?.click()
}

function handleFile(event: Event) {
  if (isRecognizing.value) return
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  productImage.value = URL.createObjectURL(file)
  notice.value = '图片已上传，正在识别商品信息…'
  recognize(file)
}

async function recognize(file: File) {
  if (isRecognizing.value) return
  isRecognizing.value = true
  notice.value = '图片已上传，AI 正在识别商品信息…'
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
    const confidence = typeof data.recognition_confidence === 'number' ? data.recognition_confidence : 0
    notice.value = confidence > 0 && confidence < 0.78 ? `AI 识别为「${data.name}」，但置信度较低，请重点复核品类` : 'AI 已识别商品信息，你可以继续编辑'
  } catch (error) {
    notice.value = staticPreview ? '静态预览模式：这里会连接真实 AI 识别服务' : (error instanceof Error ? error.message : '图片识别失败，请稍后重试')
  } finally {
    isRecognizing.value = false
  }
}

async function generate() {
  if (isGenerating.value) return
  isGenerating.value = true
  notice.value = 'AI 正在根据商品信息生成整套素材…'
  try {
    if (staticPreview) {
      if (creditBalance.value < 1) throw new Error('生成额度不足，请购买额度包')
      await new Promise((resolve) => window.setTimeout(resolve, 500))
      creditBalance.value -= 1
      results.value = results.value.map((asset) => ({ ...asset, title: asset.kind === 'main' ? product.value.name : asset.title }))
      generations.value = [{ ...generations.value[0], assets: results.value, count: results.value.length, product_name: product.value.name, created_at: new Date().toISOString() }]
      libraryAssets.value = results.value.map((asset, index) => ({ ...asset, id: `preview-asset-${index + 1}`, product_name: product.value.name }))
      notice.value = `预览生成完成，已扣除 1 次额度，剩余 ${creditBalance.value} 次`
      return
    }
    await saveProduct()
    const response = await fetch(`${API_BASE}/generations`, {
      method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ product: product.value, usage: activeUsage.value, style: activeStyle.value, tone: activeTone.value, composition: activeComposition.value, background: activeBackground.value, platform: activePlatform.value }),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || '生成失败，请稍后重试')
    }
    const data = await response.json()
    if (Array.isArray(data.assets) && data.assets.length) results.value = data.assets
    await loadWorkspaceData()
    await loadBilling()
    notice.value = '生成完成，素材已准备好'
  } catch (error) {
    notice.value = staticPreview ? '静态预览模式：这里会连接真实 AI 生图服务' : (error instanceof Error ? error.message : '生成失败，请稍后重试')
  } finally {
    isGenerating.value = false
  }
}

function downloadAsset(asset: Result) {
  void downloadComposedAsset(asset)
}

function downloadAll() {
  results.value.forEach((asset, index) => window.setTimeout(() => downloadAsset(asset), index * 350))
  notice.value = '正在下载全部素材'
}

function assetOverlay(asset: Result) {
  const name = posterCopy.value.title.trim() || asset.product_name || product.value.name || asset.title
  const defaultMeta = [asset.product_origin || product.value.origin, asset.product_spec || product.value.spec].filter(Boolean).join(' · ')
  const meta = posterCopy.value.subtitle.trim() || defaultMeta
  const customTags = posterCopy.value.tags.split(/[、,，|｜]/).map((tag) => tag.trim()).filter(Boolean)
  const tags = (customTags.length ? customTags : (asset.product_tags?.length ? asset.product_tags : product.value.tags)).slice(0, 4)
  return { name, meta, tags, badge: asset.badge || '商品主图' }
}

function posterKicker(asset: Result) {
  return `${posterCopy.value.kicker.trim() || currentPosterTheme.value.kicker}  ·  ${asset.badge || '商品主图'}`
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('图片加载失败'))
    image.src = url
  })
}

async function downloadComposedAsset(asset: Result) {
  try {
    const image = await loadImage(asset.image)
    const canvas = document.createElement('canvas')
    canvas.width = image.naturalWidth || image.width
    canvas.height = image.naturalHeight || image.height
    const context = canvas.getContext('2d')
    if (!context || !canvas.width || !canvas.height) throw new Error('无法创建合成画布')
    context.drawImage(image, 0, 0, canvas.width, canvas.height)

    const copy = assetOverlay(asset)
    const theme = currentPosterTheme.value
    const padding = Math.max(28, Math.round(canvas.width * 0.055))
    const titleSize = Math.max(28, Math.round(canvas.width * 0.038))
    const metaSize = Math.max(16, Math.round(canvas.width * 0.019))
    const kickerSize = Math.max(13, Math.round(canvas.width * 0.014))
    const panelTop = Math.round(canvas.height * 0.64)
    const panelRgb = theme.panel.match(/[\da-f]{2}/gi)?.map((value) => parseInt(value, 16)) || [5, 25, 11]
    const gradient = context.createLinearGradient(0, panelTop - canvas.height * 0.12, 0, canvas.height)
    gradient.addColorStop(0, `rgba(${panelRgb.join(',')}, 0)`)
    gradient.addColorStop(0.35, `rgba(${panelRgb.join(',')}, 0.68)`)
    gradient.addColorStop(1, `rgba(${panelRgb.join(',')}, 0.96)`)
    context.fillStyle = gradient
    context.fillRect(0, panelTop - canvas.height * 0.12, canvas.width, canvas.height - panelTop + canvas.height * 0.12)
    context.fillStyle = theme.accent
    context.fillRect(padding, panelTop + 18, Math.max(5, Math.round(canvas.width * 0.006)), Math.round(canvas.height * 0.16))
    context.fillStyle = theme.meta
    context.textBaseline = 'alphabetic'
    context.font = `600 ${kickerSize}px "Noto Sans SC", "Microsoft YaHei", sans-serif`
    context.fillText(`${posterCopy.value.kicker.trim() || theme.kicker}  ·  ${copy.badge}  ·  鲜图 AI`, padding + 18, panelTop + 33)
    context.fillStyle = '#ffffff'
    context.font = `700 ${titleSize}px "Noto Sans SC", "Microsoft YaHei", sans-serif`
    context.fillText(copy.name, padding + 18, panelTop + 78)
    context.font = `400 ${metaSize}px "Noto Sans SC", "Microsoft YaHei", sans-serif`
    if (copy.meta) context.fillText(copy.meta, padding + 18, panelTop + 108)
    let tagX = padding + 18
    const tagY = panelTop + 125
    context.font = `500 ${Math.max(13, Math.round(metaSize * 0.78))}px "Noto Sans SC", "Microsoft YaHei", sans-serif`
    for (const tag of copy.tags) {
      const tagWidth = context.measureText(tag).width + 18
      if (tagX + tagWidth > canvas.width - padding) break
      const tagRgb = theme.tag.match(/[\da-f]{2}/gi)?.map((value) => parseInt(value, 16)) || [31, 154, 89]
      context.fillStyle = `rgba(${tagRgb.join(',')}, 0.86)`
      context.fillRect(tagX, tagY - 15, tagWidth, 24)
      context.fillStyle = theme.meta
      context.fillText(tag, tagX + 9, tagY + 2)
      tagX += tagWidth + 8
    }

    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92))
    if (!blob) throw new Error('图片合成失败')
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `${copy.name || asset.title}.jpg`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000)
    notice.value = `已下载带文字信息的「${copy.name || asset.title}」`
  } catch {
    const link = document.createElement('a')
    link.href = asset.image
    link.download = `${asset.title}.jpg`
    link.target = '_blank'
    link.click()
    notice.value = `已下载原图「${asset.title}」，跨域图片无法合成文字`
  }
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
    <div v-if="showBilling" class="billing-overlay" @click.self="showBilling = false">
      <section class="billing-modal">
        <button class="billing-close" @click="showBilling = false">×</button>
        <span class="eyebrow">PAYPAL CREDIT PACKS</span>
        <h2>购买生成额度</h2>
        <p class="billing-subtitle">当前余额 <b>{{ creditBalance }}</b> 次 · 一次购买，不自动续费</p>
        <div class="billing-grid">
          <article v-for="plan in creditPlans" :key="plan.code" class="billing-card">
            <h3>{{ plan.name }}</h3><p>{{ plan.description }}</p><strong>{{ plan.credits }} 次</strong><span>{{ plan.currency }} {{ plan.amount }}</span>
            <div :id="`paypal-button-${plan.code}`" class="paypal-button-slot"></div>
            <button v-if="staticPreview && !paypalClientId" :disabled="billingLoading" @click="purchasePlan(plan)">{{ billingLoading ? '处理中…' : '本地模拟购买' }}</button>
            <small v-else-if="!paypalClientId" class="paypal-unavailable">PayPal 尚未启用，请联系管理员</small>
          </article>
        </div>
        <small class="billing-note">支付由 PayPal 处理，额度仅在 PayPal 支付完成后到账。</small>
      </section>
    </div>
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
          <div class="crown">♛</div><strong>生成额度</strong>
          <p>当前剩余 {{ creditBalance }} 次<br />购买额度包即可继续创作</p>
          <button @click="openBilling">购买额度</button>
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
            <div class="product-card"><div class="product-thumb"><img :src="productImage" alt="商品图片" /><button class="remove" :disabled="isRecognizing">×</button></div><div class="product-summary"><b>{{ product.name }}</b><span>{{ product.spec }} / 精品装</span><button class="outline-btn" :disabled="isRecognizing" @click="triggerUpload">{{ isRecognizing ? '✦ AI 识别中…' : '↥　更换图片' }}</button></div></div>
            <input ref="fileInput" type="file" accept="image/*" hidden @change="handleFile" />
            <div class="section-label">商品信息 <small>（AI自动识别，可编辑）</small></div>
            <label class="field"><span>商品名称</span><input v-model="product.name" maxlength="30" /><i>{{ product.name.length }}/30</i></label>
            <div class="field tag-field"><span>卖点标签</span><div class="tags"><button v-for="tag in ['果大','脆甜','新鲜','当季']" :key="tag" :class="{ chosen: product.tags.includes(tag) }" @click="toggleTag(tag)">{{ tag }}</button><button class="plus" @click="product.tags.push('精选')">＋</button></div></div>
            <label class="field"><span>产地</span><input v-model="product.origin" /></label>
            <label class="field"><span>规格</span><input v-model="product.spec" /></label>
            <div class="ai-hint" :class="{ recognizing: isRecognizing, 'needs-review': !isRecognizing && product.recognition_confidence && product.recognition_confidence < 0.78 }">{{ isRecognizing ? '✦　AI 正在分析图片，请稍候…' : (product.recognition_confidence && product.recognition_confidence < 0.78 ? '⚠　识别置信度较低，请确认商品名称' : '♧　AI 已智能识别商品信息，您也可以手动修改') }}<br /><small>{{ isRecognizing ? '通常需要 5 秒左右，完成后可继续编辑。' : (product.recognition_evidence || '让图片更符合你的需求。') }}</small></div>
            <button class="save-product-btn" @click="saveProduct">保存商品信息</button>
          </section>

          <section class="panel control-panel">
            <div class="step-title"><span>2</span><div><b>选择图片用途</b><small>AI 会根据用途自动匹配最佳风格与构图</small></div></div>
            <div class="usage-grid"><button v-for="usage in usages" :key="usage.id" class="usage-card" :class="{ chosen: activeUsage === usage.id }" @click="activeUsage = usage.id"><span class="usage-icon">{{ usage.icon }}</span><b>{{ usage.title }}</b><small>{{ usage.desc }}</small><em v-if="activeUsage === usage.id">✓</em></button></div>
            <div class="step-title style-step"><span>3</span><div><b>选择风格</b><small>AI 会根据商品自动推荐合适的风格</small></div></div>
            <div class="style-scroll"><button v-for="style in styles" :key="style.id" class="style-card" :class="{ chosen: activeStyle === style.id }" @click="activeStyle = style.id"><div><img :src="style.image" alt="" /><em v-if="style.tag">{{ style.tag }}</em></div><b>{{ style.title }}</b></button></div>
            <div class="personalization">
              <div class="personalization-title"><span>✦ 个性化参数</span><small>让每次生成更贴合渠道与场景</small></div>
              <div class="parameter-group"><span>画面气质</span><div class="parameter-options"><button v-for="item in tones" :key="item.id" :class="{ chosen: activeTone === item.id }" @click="activeTone = item.id">{{ item.title }}</button></div></div>
              <div class="parameter-group"><span>构图方式</span><div class="parameter-options"><button v-for="item in compositions" :key="item.id" :class="{ chosen: activeComposition === item.id }" @click="activeComposition = item.id">{{ item.title }}</button></div></div>
              <div class="parameter-group"><span>背景场景</span><div class="parameter-options"><button v-for="item in backgrounds" :key="item.id" :class="{ chosen: activeBackground === item.id }" @click="activeBackground = item.id">{{ item.title }}</button></div></div>
              <div class="parameter-group"><span>发布渠道</span><div class="parameter-options"><button v-for="item in platforms" :key="item.id" :class="{ chosen: activePlatform === item.id }" @click="activePlatform = item.id">{{ item.title }}</button></div></div>
            </div>
            <button class="generate-btn" :class="{ loading: isGenerating }" @click="generate"><span>{{ isGenerating ? '✦ 正在生成，请稍候…' : '✦ 一键生成整套图片　→' }}</span></button><p class="time-tip">预计耗时 30-60 秒</p>
          </section>

          <section class="panel result-panel">
            <div class="result-header"><div class="step-title compact"><span class="sparkle">✦</span><div><b>生成结果</b><small>{{ generatedCopy }}</small></div></div><button class="refresh" @click="generate">⟳　重新生成</button></div>
            <div class="poster-theme-picker"><div class="poster-theme-heading"><b>海报模板</b><small>预览与下载会同步使用</small></div><div class="poster-theme-options"><button v-for="theme in posterThemes" :key="theme.id" class="poster-theme-option" :class="[{ chosen: activePosterTheme === theme.id }, `theme-${theme.id}`]" @click="activePosterTheme = theme.id"><i></i><span>{{ theme.title }}</span><small>{{ theme.desc }}</small></button></div><div class="poster-copy-editor"><label><span>眉标</span><input v-model="posterCopy.kicker" maxlength="20" placeholder="跟随模板文案" /></label><label><span>主标题</span><input v-model="posterCopy.title" maxlength="30" :placeholder="product.name || '商品名称'" /></label><label><span>副文案</span><input v-model="posterCopy.subtitle" maxlength="50" placeholder="产地 · 规格" /></label><label><span>标签</span><input v-model="posterCopy.tags" maxlength="60" placeholder="用、分隔，例如：鲜甜、当季" /></label><button class="copy-reset" @click="posterCopy = { kicker: '', title: '', subtitle: '', tags: '' }">恢复默认</button></div></div>
            <div v-if="results.length" class="result-grid"><article v-for="asset in results" :key="asset.id || asset.title" class="result-card" :class="[asset.kind, `poster-${activePosterTheme}`]"><img :src="asset.image" alt="生成结果" /><div class="result-overlay"><span>{{ asset.badge }}</span><button :aria-label="`下载${asset.badge}`" @click="downloadAsset(asset)">↓</button></div><div class="asset-text-layer"><span class="poster-kicker">{{ posterKicker(asset) }}　·　鲜图 AI</span><strong>{{ assetOverlay(asset).name }}</strong><small v-if="assetOverlay(asset).meta">{{ assetOverlay(asset).meta }}</small><div v-if="assetOverlay(asset).tags.length" class="asset-tags"><span v-for="tag in assetOverlay(asset).tags" :key="tag">{{ tag }}</span></div></div></article></div>
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
