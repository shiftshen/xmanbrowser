import { useSyncExternalStore } from "react";

export type Lang = "en" | "zh";

// Translation table. Keys are stable ids; English is the source/fallback.
const DICT: Record<Lang, Record<string, string>> = {
  en: {
    "nav.profiles": "Profiles",
    "nav.allProfiles": "All profiles",
    "nav.newGroup": "New group",
    "nav.network": "Network",
    "nav.proxyPool": "Proxy pool",
    "nav.getProxies": "Get clean proxies",
    "status.connecting": "connecting…",
    "status.connected": "connected",
    "status.starting": "starting…",
    "tb.search": "Search…",
    "tb.launchAll": "▶ Launch all",
    "tb.stopAll": "■ Stop all",
    "tb.import": "Import",
    "tb.export": "Export",
    "tb.newProfile": "＋ New profile",
    "tb.detect": "🛡 Check",
    "tb.detecting": "Checking…",
    "tb.testAll": "🛡 Check all",
    "tb.bulkImport": "Bulk import",
    "tb.addProxy": "＋ Add proxy",
    "card.system": "System",
    "card.webgl": "WebGL",
    "card.proxy": "Proxy",
    "card.cores": "cores",
    "card.noProxy": "none (direct)",
    "card.launch": "Launch",
    "card.stop": "Stop",
    "card.edit": "Edit",
    "card.clone": "Clone",
    "card.check": "🛡 Check",
    "card.checking": "Checking…",
    "card.running": "running",
    "empty.title": "No profiles {0}",
    "empty.titleYet": "yet",
    "empty.titleIn": "in “{0}”",
    "empty.hint": "Click ＋ New profile to create one — it gets an auto name and a fresh fingerprint.",
    "det.title": "Check result",
    "det.subDirect": "no proxy · direct (this machine's IP)",
    "det.subProxy": "via this environment's proxy exit",
    "det.subCurrent": "current egress IP",
    "det.rating.clean": "clean",
    "det.rating.risky": "risky",
    "det.rating.flagged": "flagged",
    "det.fail": "Check failed: {0}",
    "det.row.ipRegion": "IP / region",
    "det.row.isp": "ISP",
    "det.row.ipType": "IP type",
    "det.row.proxyCheck": "Proxy/VPN check",
    "det.row.hosting": "Hosting / datacenter",
    "det.type.residential": "residential",
    "det.type.mobile": "mobile — cleanest",
    "det.type.datacenter": "datacenter — easily flagged",
    "det.type.unknown": "unknown",
    "det.proxy.flagged": "flagged as proxy/VPN",
    "det.proxy.clean": "not flagged",
    "det.hosting.hit": "in a hosting range",
    "det.cta": "IP not clean? Get a 711Proxy residential IP →",
    "offers.hint": "Need clean IPs? Datacenter/VPN IPs get flagged — residential & 4G pass anti-fraud.",
    "offers.button": "Get residential / 4G / ISP proxies ▾",
    "offers.disclosure": "Affiliate links — buying through them supports development.",
    "offer.tier.711": "Premium residential",
    "offer.sub.711": "90M+ residential IPs · anti-fraud grade",
    "offer.tier.webshare": "Budget · free tier",
    "offer.sub.webshare": "10 free proxies · pay-as-you-grow · card/PayPal",
    "prov.title": "Providers",
    "prov.subtitle": "auto-fetch proxies from an API or rotating gateway",
    "prov.add": "＋ Add provider",
    "prov.empty": "No providers. Add one to pull proxies automatically instead of pasting them.",
    "dlg.confirm": "Confirm",
    "dlg.delete": "Delete",
    "dlg.cancel": "Cancel",
    "dlg.ok": "OK",
    "dlg.deleteProfile": "Delete \"{0}\" and its data?",
    "dlg.deleteProxy": "Delete proxy \"{0}\"?",
    "dlg.deleteProvider": "Delete provider \"{0}\"?",
    "dlg.newGroupName": "New group name:",
    "dlg.newGroupPlaceholder": "e.g. shop-accounts",
    "lang.toggle": "中文",
  },
  zh: {
    "nav.profiles": "环境",
    "nav.allProfiles": "全部环境",
    "nav.newGroup": "新建分组",
    "nav.network": "网络",
    "nav.proxyPool": "代理池",
    "nav.getProxies": "获取干净代理",
    "status.connecting": "连接中…",
    "status.connected": "已连接",
    "status.starting": "启动中…",
    "tb.search": "搜索…",
    "tb.launchAll": "▶ 全部启动",
    "tb.stopAll": "■ 全部停止",
    "tb.import": "导入",
    "tb.export": "导出",
    "tb.newProfile": "＋ 新建环境",
    "tb.detect": "🛡 一键检测",
    "tb.detecting": "检测中…",
    "tb.testAll": "🛡 一键检测",
    "tb.bulkImport": "批量导入",
    "tb.addProxy": "＋ 添加代理",
    "card.system": "系统",
    "card.webgl": "显卡",
    "card.proxy": "代理",
    "card.cores": "核",
    "card.noProxy": "无（直连）",
    "card.launch": "启动",
    "card.stop": "停止",
    "card.edit": "编辑",
    "card.clone": "克隆",
    "card.check": "🛡 检测",
    "card.checking": "检测中…",
    "card.running": "运行中",
    "empty.title": "没有环境{0}",
    "empty.titleYet": "",
    "empty.titleIn": "（分组「{0}」）",
    "empty.hint": "点 ＋ 新建环境 创建一个 —— 自动命名、自动生成全新指纹。",
    "det.title": "检测结果",
    "det.subDirect": "无代理 · 直连本机 IP",
    "det.subProxy": "经此环境的代理出口",
    "det.subCurrent": "当前出口 IP",
    "det.rating.clean": "干净",
    "det.rating.risky": "有风险",
    "det.rating.flagged": "已被标记",
    "det.fail": "检测失败：{0}",
    "det.row.ipRegion": "IP / 地区",
    "det.row.isp": "ISP",
    "det.row.ipType": "IP 类型",
    "det.row.proxyCheck": "代理/VPN 检测",
    "det.row.hosting": "托管/机房",
    "det.type.residential": "住宅 (residential)",
    "det.type.mobile": "移动 (mobile) — 最干净",
    "det.type.datacenter": "数据中心 (datacenter) — 易被风控",
    "det.type.unknown": "未知",
    "det.proxy.flagged": "被标记为 proxy/VPN",
    "det.proxy.clean": "未被标记",
    "det.hosting.hit": "命中 hosting 段",
    "det.cta": "IP 不够干净？换 711Proxy 住宅 IP →",
    "offers.hint": "需要干净 IP？数据中心/VPN 的 IP 会被风控标记 —— 住宅 & 4G 才能过反欺诈。",
    "offers.button": "获取住宅 / 4G / ISP 代理 ▾",
    "offers.disclosure": "联盟链接 —— 通过它们购买可支持本项目开发。",
    "offer.tier.711": "高质量住宅",
    "offer.sub.711": "9000万+住宅IP · 中文/支付宝 · 抗风控",
    "offer.tier.webshare": "便宜入门",
    "offer.sub.webshare": "免费10个代理起 · 按量计费 · 卡/PayPal",
    "prov.title": "代理提供商",
    "prov.subtitle": "从 API 或轮换网关自动拉取代理",
    "prov.add": "＋ 添加提供商",
    "prov.empty": "暂无提供商。添加一个即可自动拉取代理,不用手动粘贴。",
    "dlg.confirm": "确认",
    "dlg.delete": "删除",
    "dlg.cancel": "取消",
    "dlg.ok": "确定",
    "dlg.deleteProfile": "删除「{0}」及其数据？",
    "dlg.deleteProxy": "删除代理「{0}」？",
    "dlg.deleteProvider": "删除提供商「{0}」？",
    "dlg.newGroupName": "新分组名称：",
    "dlg.newGroupPlaceholder": "例如 shop-accounts",
    "lang.toggle": "EN",
  },
};

const KEY = "xman_lang";
function detect(): Lang {
  try {
    const saved = localStorage.getItem(KEY) as Lang | null;
    if (saved === "en" || saved === "zh") return saved;
  } catch { /* ignore */ }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

let lang: Lang = detect();
const listeners = new Set<() => void>();

export function setLang(l: Lang) {
  lang = l;
  try { localStorage.setItem(KEY, l); } catch { /* ignore */ }
  listeners.forEach((fn) => fn());
}
export function getLang(): Lang { return lang; }
function subscribe(fn: () => void) { listeners.add(fn); return () => listeners.delete(fn); }

function fmt(s: string, args: (string | number)[]) {
  return s.replace(/\{(\d+)\}/g, (_, i) => String(args[Number(i)] ?? ""));
}

/** Hook: returns a `t(key, ...args)` bound to the current language; components
 *  re-render automatically when the language is toggled. */
export function useT() {
  useSyncExternalStore(subscribe, getLang, getLang);
  return (key: string, ...args: (string | number)[]) => {
    const s = DICT[lang][key] ?? DICT.en[key] ?? key;
    return args.length ? fmt(s, args) : s;
  };
}
