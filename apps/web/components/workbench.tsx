"use client";
import { IdentityContractBadge, IdentityContractEvidence, identityContractText } from "./identity-contract";
import { FieldResolutionView } from "./field-authority";
import { fieldDefaultText, fieldValueText } from "./field-authority-values";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeItem, Evidence, Health, LifecycleReview, ExcludedVariant, QueryResult, SaveComparisonRequest, Source, SourceFieldConflict, TireQuery, Variant, WatchItem } from "@tire/domain-types";
import { tireApi } from "@tire/api-client";
import { Icon, type IconName } from "./icons";
import VehicleFitments from "./vehicle-fitments";
import SourceQuality from "./source-quality";
import SourceManagement from "./source-management";
import MonitorTaskCenter from "./task-center";
import { canFetchSource, canQuerySource } from "./source-management-values";
import { SourceAccessProvider, useSourceAccess } from "./source-status";
import FactReviewDialog from "./fact-review";
import VariantLifecycleDialog from "./variant-lifecycle";
import IdentityReviewDialog, { identityLabel } from "./identity-review";
import type { IdentityMapping, IdentityReview } from "@tire/domain-types";
import GarageWorkspace, { AssignTireDialog, SaveFitmentDialog } from "./garage";
import { SavedComparisonsPanel, SaveComparisonDialog } from "./research";
import MonitoringCenter from "./monitoring";
import PwaStatus from "./pwa-status";
import TestEvents from "./test-events";
import AIAnalysisDialog, { type AITarget } from "./ai-analysis";
import ReportsDialog from "./reports";
import KnowledgeSearchDialog from "./knowledge-search";
import LocalFallbackPanel from "./local-fallback-panel";
import { createDeviceOffer, type LocalFallbackOffer } from "./local-fallback-controller";
import QueryFallbackPolicy from "./query-fallback-policy";
import OfflineLibraryDialog, { OfflineLibraryEntry } from "./offline-library";
import { DeviceAiEntry } from "./device-ai-panel";
import DeviceSyncLifecycle from "./device-sync-lifecycle";
import type { OfflineReference } from "@tire/domain-types";
import RecallDialog from "./recalls";
import QueryFilters, { describeFilter, parseFilterDrafts, QuerySelectionCounts, type FilterDraft } from "./query-filters";
import type { TireFilter, TireFilterCatalog } from "@tire/domain-types";
import { browserPlatform, WorkbenchPlatformContext, useWorkbenchPlatform, type WorkbenchPlatform } from "./workbench-platform";

type View = "query" | "vehicles" | "garage" | "compare" | "watch" | "sources";
type SourceRun = { source: Source; loading: boolean; data?: QueryResult; error?: string; consentPending?: boolean; denied?: boolean };
type ActiveQuery = { query: TireQuery; filters: readonly TireFilter[]; sources: Source[]; accessGenerations: Record<string, number>; fallbackEligible: Record<string, boolean>; attempts: Record<string, string>; fallbackGeneration: number; fallbackDraft: string; generation: number; controller: AbortController };
const hasQueryData = (data?: QueryResult) => !!data && ["live", "live_verified_304", "local_snapshot"].includes(data.data_state);
const navigation: { id: View; label: string; english: string; icon: IconName }[] = [
  { id: "query", label: "轮胎查询", english: "EXPLORER", icon: "search" },
  { id: "vehicles", label: "车型适配", english: "FITMENTS", icon: "vehicle" },
  { id: "garage", label: "我的车库", english: "GARAGE", icon: "vehicle" },
  { id: "compare", label: "规格比较", english: "COMPARE", icon: "compare" },
  { id: "watch", label: "我的关注", english: "WATCHLIST", icon: "bookmark" },
  { id: "sources", label: "来源与证据", english: "SOURCES", icon: "source" },
];
const stateLabels: Record<string, string> = {
  live: "实时核验", live_verified_304: "在线验证 · 304", consent_required: "等待本次授权",
  source_unavailable: "来源不可用", local_snapshot: "LOCAL SNAPSHOT · 历史快照",
};
const reasonLabels: Record<string, string> = {
  disabled: "当前来源已停用，暂时无法在线查询。",
  configuration_required: "当前来源尚未完成必要配置，暂时无法查询。",
  not_implemented: "当前来源尚未接入，暂时无法查询。",
  source_rate_limited: "来源暂时限制了请求频率，请稍后重试。",
  circuit_open: "来源连续请求失败，系统正在暂停请求，请稍后重试。",
  robots_disallowed: "来源的抓取规则不允许访问本次查询页面。",
  upstream_timeout: "来源响应超时，暂时无法完成在线核验。",
  upstream_network_error: "暂时无法连接来源，请稍后重试。",
  parser_schema_changed: "来源页面未通过解析校验，需要重新核验。",
  parser_timeout: "来源内容解析超时，本次核验未完成，请稍后重试。",
  parser_cancelled: "本次来源解析已取消，未采纳新的参数。",
  parser_isolation_unavailable: "本机解析环境暂时不可用，未完成在线核验。",
  parser_failed: "来源内容解析未完成，需要检查解析记录。",
  parser_crashed: "来源内容解析意外中断，本次核验未完成。",
  parser_code_mismatch: "解析代码与已固定版本不一致，需要核对解析器部署。",
  parser_protocol_invalid: "解析结果未通过完整性校验，本次参数未被采纳。",
  source_schema_validation_failed: "来源参数未通过数据结构校验，需要重新核验。",
  evidence_capture_failed: "原文保存未完成，本次参数未被采纳，请稍后重试。",
  unsupported_model: "当前来源暂不支持所选型号，请选择已支持的型号。",
  source_size_required: "当前来源按尺寸提供规格，请填写轮胎尺寸后重新查询。",
  invalid_size: "轮胎尺寸不符合当前来源支持的公制格式，请核对后重新查询。",
  source_disabled: "当前来源已停用，暂时无法在线查询。",
  source_paused: "来源已在本机暂停，历史证据仍可读取。",
  source_archived: "来源已在本机归档，历史证据仍可读取。",
  source_access_changed: "来源状态已变化，旧在线请求及待答授权已失效，请重新查询。",
  source_access_pin_missing: "旧请求没有当前来源授权，请重新查询。",
  vehicle_generation_not_verified: "该代际的官方配置来源尚待核验，不使用其他代际的数据代替。",
  vehicle_generation_not_found: "官方来源暂未返回该代际的明确配置。",
  vehicle_generation_identity_changed: "官方车型代际标识发生变化，需要重新核验来源。",
  vehicle_source_fetch_failed: "车型官方来源暂时无法连接，请稍后重试。",
  vehicle_source_schema_changed: "车型官方配置表结构发生变化，需要更新解析器后重新核验。",
  vehicle_network_unavailable: "车型来源网络暂时不可用，请稍后重试。",
  no_matching_vehicle_snapshot: "本地没有匹配该车型的历史配置。",
  source_quality_quarantined: "来源数据出现明显缺失或无法可靠对应，已暂停本次数据更新。异常内容已留存待核验，不作为正式参数使用。",
};
const statusLabels: Record<string, string> = {
  enabled: "已启用", active: "已启用", available: "可查询", configured: "已配置", ready: "可查询",
  disabled: "未启用", unavailable: "暂不可用", configuration_required: "待配置", planned: "待接入", not_implemented: "待接入",
  paused: "本机已暂停", archived: "本机已归档", source_paused: "本机已暂停", source_archived: "本机已归档",
};
const isQueryableSource = (source: Source) => (!source.target_kind || source.target_kind === "tire") && (source.source_setting ? canQuerySource(source.source_setting, true) : ["ready", "available", "enabled"].includes(source.status));
const supportsModel = (source: Source, model: string) => !source.supported_models || source.supported_models.includes(model);
const regionLabels: Record<string, string> = { CN: "中国", US: "美国", UK: "英国", FR: "法国", DE: "德国", EU: "欧盟" };
const factLabels: Record<string, string> = {
  wet_grip: "湿地抓地等级", fuel_efficiency: "燃油效率等级", noise_db: "外部滚动噪音", noise_class: "噪音等级",
  treadwear: "磨耗指数", traction: "牵引力等级", temperature: "耐热等级", warranty_miles: "里程质保", weight: "重量",
  gtin: "商品条码", construction: "结构", oe_vehicle_scope: "原配品牌列表", technology_features: "技术标记",
  pncs: "PNCS 声明", elect: "ELECT 标识", ev_marketing_mark: "EV 营销标识",
  runforward: "RUNFORWARD 声明", self_sealing: "自密封声明", cyber: "CYBER 标识",
  weight_kg: "重量", tread_depth: "胎纹深度", season: "季节", service_description: "原始规格",
  product_code_type: "来源声明的编码类型", utqg_treadwear: "UTQG 磨耗指数", utqg_traction: "UTQG 牵引力等级", utqg_temperature: "UTQG 耐热等级",
  source_utqg_raw: "UTQG 来源原串（待核验）", source_utqg_components: "UTQG 原始分项",
  eu_fuel_class: "欧盟能效等级", eu_wet_grip: "欧盟湿地抓地等级", eu_external_noise_db: "欧盟外部噪声", eu_noise_class: "欧盟噪声等级",
  source_markings: "来源规格标记", source_size_designation: "原始尺寸标记",
  source_technology_marking: "厂商技术标记", mspn: "MSPN 产品编号", cai: "CAI 产品编号", eu_directive_number: "欧盟指令编号",
  load_id: "负载等级标记", weight_lb: "重量（磅）", max_load_lb: "最大载重（磅）", max_pressure_psi: "最大胎压（psi）",
  overall_diameter_in: "外径（英寸）", overall_width_in: "总宽（英寸）", revolutions_per_mile: "每英里转数",
  rim_width_range_in: "适用轮辋宽度（英寸）", recommended_rim_width_in: "推荐轮辋宽度（英寸）", sidewall_code: "胎侧标记",
  tread_construction: "胎面结构", sidewall_construction: "胎侧结构", for_sale: "来源在售状态",
  acoustic_foam: "静音泡棉", m_plus_s: "M+S 泥雪标记", three_peak_mountain_snowflake: "三峰雪花标记（3PMSF）",
  sealant: "自密封胶", studded: "防滑钉", ply_rating: "层级（PR）", manufacturing_origin: "制造地",
};
const hiddenFacts = new Set(["evidence_spans", "source_updated_at", "source_start_date", "source_end_date", "weights", "tread_depths", "active", "source_field_conflicts", "source_field_anomalies", "source_utqg_components", "source_extra_load", "source_high_load", "source_model_name", "source_labelling"]);
const asConflicts = (value: unknown): SourceFieldConflict[] => Array.isArray(value) ? value.filter((item): item is SourceFieldConflict => !!item && typeof item === "object" && typeof item.field === "string" && Array.isArray(item.values)) : [];
const variantConflicts = (variant: Variant) => asConflicts(variant.facts?.source_field_conflicts);
const variantAnomalies = (variant: Variant): { field: string; raw_value: unknown; reason?: string }[] => {
  const value = variant.facts?.source_field_anomalies;
  return Array.isArray(value) ? value.filter(item => item && typeof item === "object" && typeof item.field === "string") : [];
};
const hasFieldConflict = (variant: Variant, field: string) => variantConflicts(variant).some(conflict => conflict.field === field && conflict.resolution !== "resolved");
const conflictFieldLabel = (field: string) => ({ xl: "XL 加强型", hl: "HL 高载重", oe_mark: "原厂 OE 标记", run_flat: "防爆技术", acoustic_technology: "静音技术" }[field] || factLabels[field] || field);
const visibleFacts = (facts: Record<string, unknown>, productCode?: string | null) => Object.entries(facts).filter(([key, value]) => !hiddenFacts.has(key) && !(["cai", "mspn"].includes(key) && value === productCode));
const missingValue = "来源未标明";
const isMissingValue = (value: unknown) => value === null || value === undefined || (typeof value === "string" && ["", "unknown", "unspecified"].includes(value.trim().toLowerCase()));
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";
const isAbort = (error: unknown) => error instanceof Error && error.name === "AbortError";
const displayValue = (value: unknown): string => {
  if (isMissingValue(value)) return missingValue;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.length ? value.map(displayValue).join("、") : missingValue;
  if (value && typeof value === "object") {
    if ("value" in value) return isMissingValue(value.value) ? missingValue : `${displayValue(value.value)}${"unit" in value && value.unit ? ` ${String(value.unit)}` : ""}`;
    return "结构化记录 · 详见证据";
  }
  return String(value);
};
const formatFactValue = (key: string, value: unknown): string => {
  if (isMissingValue(value)) return missingValue;
  if (key === "weight_kg") {
    const amount = value && typeof value === "object" && "value" in value ? value.value : value;
    return isMissingValue(amount) ? missingValue : `${displayValue(amount)} kg`;
  }
  if (key === "tread_depth" && value && typeof value === "object" && "value" in value) {
    if (isMissingValue(value.value)) return missingValue;
    const unit = "unit" in value ? String(value.unit).trim() : "";
    if (/^(?:\/?32(?:nds?|ndsof(?:an)?inch)?|1\/32(?:inch|in|\")?|\/32(?:inch|in|\")|32(?:th|nd)(?:inch|in))$/i.test(unit.replace(/[\s.]/g, ""))) return `${displayValue(value.value)}/32 英寸（来源单位）`;
    if (/^(?:inch|inches|in|\")$/i.test(unit)) return `${displayValue(value.value)} 英寸`;
  }
  if (key === "season" && typeof value === "string") {
    const seasons: Record<string, string> = { summer: "夏季", winter: "冬季", allseason: "四季", allweather: "全天候" };
    return seasons[value.toLowerCase().replace(/[\s_-]/g, "")] || value;
  }
  if (key === "construction" && typeof value === "string") {
    const structures: Record<string, string> = { r: "子午线（R）", zr: "子午线（ZR）", radial: "子午线（RADIAL）", b: "带束斜交（B）", d: "斜交（D）" };
    return structures[value.toLowerCase()] || value;
  }
  return displayValue(value);
};
const formatTime = (value?: string | null) => {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
};
const safeExternalUrl = (value: string) => { try { const url = new URL(value); return url.protocol === "https:" || url.protocol === "http:" ? url.href : undefined; } catch { return undefined; } };

function TireDrawing() {
  return <svg className="tire-drawing" width="360" height="210" viewBox="0 0 360 210" fill="none" aria-hidden="true">
    <path d="M20 174h320M43 184h274M180 18v177M59 105h242" className="drawing-guide" strokeDasharray="3 5" />
    <ellipse cx="183" cy="98" rx="71" ry="80" stroke="currentColor" strokeWidth="1.4" />
    <ellipse cx="171" cy="98" rx="61" ry="79" stroke="currentColor" strokeWidth="1.4" />
    <ellipse cx="171" cy="98" rx="39" ry="55" stroke="currentColor" strokeWidth="1.4" />
    <ellipse cx="167" cy="98" rx="29" ry="45" stroke="currentColor" strokeWidth=".8" />
    <ellipse cx="171" cy="98" rx="56" ry="72" stroke="currentColor" strokeWidth=".6" strokeDasharray="2 3" />
    {Array.from({ length: 15 }, (_, i) => { const y = 27 + i * 10; const x = 204 + Math.sin((i / 14) * Math.PI) * 44; return <path key={i} d={`M${x - 10} ${y - 4}l9 4-5 6`} stroke="currentColor" strokeWidth="1.3" />; })}
    <path d="M110 29H64v25m157 87h57v-24M171 96l26-35" className="drawing-accent" />
    <circle cx="171" cy="98" r="3" className="drawing-dot" />
    <text x="44" y="69" className="drawing-label">EXACT SKU</text><text x="262" y="108" className="drawing-label">EVIDENCE</text>
    <text x="136" y="201" className="drawing-label">TRACE EVERY FACT</text>
  </svg>;
}

export default function Workbench({ platform = browserPlatform, pwa = platform.kind === "web" }: { platform?: WorkbenchPlatform; pwa?: boolean } = {}) {
  return <WorkbenchPlatformContext.Provider value={platform}><DeviceSyncLifecycle platform={platform} /><SourceAccessProvider><WorkbenchContent pwa={pwa} /></SourceAccessProvider></WorkbenchPlatformContext.Provider>;
}

function WorkbenchContent({ pwa }: { pwa: boolean }) {
  const sourceAccess = useSourceAccess();
  const refreshSources = sourceAccess.refresh;
  const platform = useWorkbenchPlatform();
  const [view, setView] = useState<View>("query");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [sources, setSources] = useState<Source[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [sourceError, setSourceError] = useState("");
  const [booting, setBooting] = useState(true);
  const [health, setHealth] = useState<Health | null>(null);
  const [size, setSize] = useState("");
  const [model, setModel] = useState("Pilot Sport EV");
  const [region, setRegion] = useState("all");
  const [runs, setRuns] = useState<SourceRun[]>([]);
  const [localOffers, setLocalOffers] = useState<LocalFallbackOffer[]>([]);
  const [visibleCounts, setVisibleCounts] = useState<Record<string, number>>({});
  const [submittedLabel, setSubmittedLabel] = useState("");
  const [filterDrafts, setFilterDrafts] = useState<FilterDraft[]>([]);
  const [filterCatalog, setFilterCatalog] = useState<TireFilterCatalog | null>(null);
  const [filterCatalogLoading, setFilterCatalogLoading] = useState(true);
  const [filterCatalogError, setFilterCatalogError] = useState("");
  const [filterCatalogRevision, setFilterCatalogRevision] = useState(0);
  const [filterValidationError, setFilterValidationError] = useState("");
  const [submittedFilterLabels, setSubmittedFilterLabels] = useState<string[]>([]);
  const [compared, setCompared] = useState<Variant[]>([]);
  const [comparison, setComparison] = useState<Variant[]>([]);
  const [comparisonConflicts, setComparisonConflicts] = useState<SourceFieldConflict[]>([]);
  const [comparisonFingerprint, setComparisonFingerprint] = useState("");
  const [savingSelection, setSavingSelection] = useState<Omit<SaveComparisonRequest, "title" | "notes"> | null>(null);
  const [savedComparisonsRevision, setSavedComparisonsRevision] = useState(0);
  const [excludedVariants, setExcludedVariants] = useState<ExcludedVariant[]>([]);
  const [lifecycleTarget, setLifecycleTarget] = useState("");
  const [identityTarget, setIdentityTarget] = useState("");
  const [recallsOpen, setRecallsOpen] = useState(false);
  const [recallCampaign, setRecallCampaign] = useState<string | undefined>();
  const [resolveIdentities, setResolveIdentities] = useState(false);
  const [identityMappings, setIdentityMappings] = useState<IdentityMapping[]>([]);
  const [latestLifecycleReview, setLatestLifecycleReview] = useState<LifecycleReview | null>(null);
  const [garageTire, setGarageTire] = useState<Variant | null>(null);
  const [garageFitment, setGarageFitment] = useState<{ snapshotId: string; fitmentId: string; label: string } | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const [includeManual, setIncludeManual] = useState(false);
  const [comparisonRevision, setComparisonRevision] = useState(0);
  const [reviewTarget, setReviewTarget] = useState<{ variant: Variant; sourceId?: string } | null>(null);
  const [aiTarget, setAiTarget] = useState<AITarget | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [offlineReferences, setOfflineReferences] = useState<OfflineReference[] | null>(null);
  const [reportsOpen, setReportsOpen] = useState(false);
  const [reportId, setReportId] = useState<string | undefined>(undefined);
  const [watches, setWatches] = useState<WatchItem[]>([]);
  const [watchError, setWatchError] = useState("");
  const [watchLoading, setWatchLoading] = useState(false);
  const [changes, setChanges] = useState<ChangeItem[]>([]);
  const [changesError, setChangesError] = useState("");
  const [pendingWatch, setPendingWatch] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [selectedSnapshot, setSelectedSnapshot] = useState("");
  const [evidenceKind, setEvidenceKind] = useState<"tire" | "vehicle">("tire");
  const searchInput = useRef<HTMLInputElement>(null);
  const evidencePanel = useRef<HTMLElement>(null);
  const evidenceReturnFocus = useRef<HTMLElement | null>(null);
  const generation = useRef(0);
  const activeQuery = useRef<ActiveQuery | null>(null);
  const evidenceController = useRef<AbortController | null>(null);
  const watchLock = useRef(new Set<string>());
  const queryDraftKey = JSON.stringify([model, size, region, selectedSources, filterDrafts]);
  const lastDraftKey = useRef(queryDraftKey);
  const currentDraftKey = useRef(queryDraftKey); currentDraftKey.current = queryDraftKey;
  const fallbackGeneration = useRef(0);
  useEffect(() => {
    if (lastDraftKey.current === queryDraftKey) return;
    lastDraftKey.current = queryDraftKey;
    fallbackGeneration.current++; setLocalOffers([]);
  }, [queryDraftKey]);
  useEffect(() => { if (view !== "query") { setLocalOffers([]); fallbackGeneration.current++; } }, [view]);
  useEffect(() => {
    // The panel immediately clears an existing result; this also blocks a
    // failure/digest still in flight from creating an offer after owner reset.
    const ownerChanged = () => { fallbackGeneration.current++; };
    window.addEventListener("tire-offline-owner-changed", ownerChanged);
    return () => window.removeEventListener("tire-offline-owner-changed", ownerChanged);
  }, []);

  useEffect(() => platform.registerBackHandler?.(() => {
    if (selectedSnapshot) {
      clearEvidence();
      requestAnimationFrame(() => {
        const target = evidenceReturnFocus.current?.isConnected ? evidenceReturnFocus.current : searchInput.current;
        target?.focus({ preventScroll: true }); target?.scrollIntoView({ block: "center" });
      });
      return true;
    }
    if (view !== "query") { setView("query"); return true; }
    return false;
  }), [platform, selectedSnapshot, view]);

  useEffect(() => { platform.onThemeChange?.(theme); }, [platform, theme]);

  const loadInitial = useCallback(async (signal: AbortSignal) => {
    setBooting(true); setSourceError("");
    // Establish the HttpOnly session before parallel requests can create competing cookies.
    try { const result = await tireApi.health(signal); if (!signal.aborted) setHealth(result); }
    catch { if (!signal.aborted) setHealth(null); }
    if (signal.aborted) return;
    const [sourceResult, watchResult] = await Promise.allSettled([tireApi.sources(signal), tireApi.watchlists(signal), refreshSources()]);
    if (signal.aborted) return;
    if (sourceResult.status === "fulfilled") {
      setSources(sourceResult.value.sources);
      setSelectedSources(previous => {
        const availableIds = sourceResult.value.sources.filter(isQueryableSource).map(source => source.id);
        const retained = previous.filter(id => availableIds.includes(id));
        return retained.length ? retained : availableIds;
      });
    } else setSourceError(errorText(sourceResult.reason));
    if (watchResult.status === "fulfilled") { setWatches(watchResult.value.items); setWatchError(""); }
    else setWatchError(errorText(watchResult.reason));
    setBooting(false);
  }, [refreshSources]);

  useEffect(() => {
    const controller = new AbortController();
    void loadInitial(controller.signal);
    try { setTheme(localStorage.getItem("tire-theme-v1") === "dark" ? "dark" : "light"); } catch { /* Storage is optional. */ }
    return () => { controller.abort(); activeQuery.current?.controller.abort(); evidenceController.current?.abort(); };
  }, [loadInitial]);

  useEffect(() => {
    if (!sourceAccess.items.length) return;
    const settings = new Map(sourceAccess.items.map(item => [item.source_id, item]));
    setSources(previous => previous.map(source => { const setting = settings.get(source.id); return setting ? { ...source, status: setting.effective_status, source_setting: setting } : source; }));
    setSelectedSources(previous => previous.filter(id => canQuerySource(settings.get(id), true)));
    const context = activeQuery.current;
    if (context && context.sources.some(source => context.accessGenerations[source.id] !== settings.get(source.id)?.management.access_generation || !canQuerySource(settings.get(source.id), true) || (context.fallbackEligible[source.id] && !canFetchSource(settings.get(source.id), true)))) {
      context.controller.abort(); generation.current++; setLocalOffers([]);
      setRuns(previous => previous.map(run => run.loading || run.data?.data_state === "consent_required" ? { ...run, loading: false, consentPending: false, data: undefined, error: "来源状态已变化，旧请求已失效。已完成证据仍可读取。" } : run));
    }
  }, [sourceAccess.items]);

  useEffect(() => {
    if (booting) return;
    const controller = new AbortController();
    setFilterCatalogLoading(true); setFilterCatalogError("");
    void tireApi.tireQueryFilters(controller.signal).then(catalog => {
      if (controller.signal.aborted) return;
      if (catalog.version !== "tire-query-filters@1" || !Array.isArray(catalog.fields) || !catalog.fields.length || !Number.isInteger(catalog.max_conditions) || catalog.max_conditions < 1 || catalog.max_conditions > 16) throw new Error("筛选目录格式不受支持");
      setFilterCatalog(catalog);
    }).catch(error => { if (!controller.signal.aborted) setFilterCatalogError(errorText(error)); })
      .finally(() => { if (!controller.signal.aborted) setFilterCatalogLoading(false); });
    return () => controller.abort();
  }, [booting, filterCatalogRevision]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setView("query"); requestAnimationFrame(() => searchInput.current?.focus());
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const comparedIds = compared.map(item => item.id).join(",");
  useEffect(() => {
    if (view !== "compare" || !comparedIds) { setComparison([]); setComparisonConflicts([]); setExcludedVariants([]); setComparisonFingerprint(""); return; }
    const controller = new AbortController();
    setComparisonLoading(true); setComparisonError(""); setComparison([]); setComparisonConflicts([]); setExcludedVariants([]); setComparisonFingerprint("");
    setIdentityMappings([]);
    tireApi.compare(comparedIds.split(","), controller.signal, includeManual, resolveIdentities).then(result => {
      if (!controller.signal.aborted) { setComparison(result.variants); setComparisonConflicts(result.conflicts || []); setExcludedVariants(result.excluded_variants || []); setComparisonFingerprint(result.fingerprint); setIdentityMappings(result.identity_mappings || []); }
    }).catch(error => { if (!controller.signal.aborted && !isAbort(error)) setComparisonError(errorText(error)); }).finally(() => { if (!controller.signal.aborted) setComparisonLoading(false); });
    return () => controller.abort();
  }, [view, comparedIds, includeManual, resolveIdentities, comparisonRevision]);

  useEffect(() => {
    if (view !== "watch") return;
    const controller = new AbortController();
    setWatchLoading(true); setWatchError(""); setChangesError("");
    void Promise.allSettled([tireApi.watchlists(controller.signal), tireApi.changes(controller.signal)]).then(([watchResult, changesResult]) => {
      if (controller.signal.aborted) return;
      if (watchResult.status === "fulfilled") setWatches(watchResult.value.items); else setWatchError(errorText(watchResult.reason));
      if (changesResult.status === "fulfilled") setChanges(changesResult.value.items); else setChangesError(errorText(changesResult.reason));
      setWatchLoading(false);
    });
    return () => controller.abort();
  }, [view]);

  function toggleTheme() {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next); try { localStorage.setItem("tire-theme-v1", next); } catch { /* Storage is optional. */ }
  }

  function updateRun(sourceId: string, currentGeneration: number, update: Partial<SourceRun>) {
    if (generation.current !== currentGeneration) return;
    setRuns(previous => previous.map(run => run.source.id === sourceId ? { ...run, ...update } : run));
  }

  async function submitQuery(event: React.FormEvent) {
    event.preventDefault();
    const parsed = parseFilterDrafts(filterDrafts, filterCatalog);
    if (parsed.error || (filterDrafts.length && (filterCatalogLoading || filterCatalogError))) {
      setFilterValidationError(parsed.error || "请先重试加载筛选目录，现有条件不会被忽略。");
      document.getElementById("query-filter-editor")?.setAttribute("open", "");
      return;
    }
    setFilterValidationError("");
    const query: TireQuery = { ...(size.trim() ? { size: size.trim().toUpperCase() } : {}), ...(model.trim() ? { model: model.trim() } : {}) };
    if (!query.size && !query.model) { searchInput.current?.focus(); setNotice("请输入轮胎尺寸或型号，再开始在线查询。"); return; }
    if (!model || !region) { setNotice("请明确选择轮胎型号和来源地区，再发起在线查询。车型尺寸不会自动推断原配 SKU。"); return; }
    const requestedSources = sources.filter(source => isQueryableSource(source) && supportsModel(source, model)
      && (region === "all" || source.region === region) && selectedSources.includes(source.id));
    if (!requestedSources.length) { setNotice("请至少选择一个支持当前型号和地区的查询来源。"); return; }
    const sizeRequiredSources = requestedSources.filter(source => source.requires_size);
    if (!query.size && sizeRequiredSources.length) {
      searchInput.current?.focus();
      setNotice(`${sizeRequiredSources.map(source => source.name).join("、")} 按尺寸查询规格，请填写轮胎尺寸。`);
      return;
    }
    await runQuery(query, parsed.filters, requestedSources);
  }

  async function offerDeviceFallback(context: ActiveQuery, source: Source, cause: unknown) {
    if (context.fallbackGeneration !== fallbackGeneration.current || context.fallbackDraft !== currentDraftKey.current) return;
    const offer = await createDeviceOffer(platform.offline, "tire", context.query, context.filters, source.id,
      context.accessGenerations[source.id], cause, context.attempts[source.id], source.name);
    if (offer && context.fallbackGeneration === fallbackGeneration.current && context.fallbackDraft === currentDraftKey.current && !context.controller.signal.aborted && generation.current === context.generation) setLocalOffers(previous => [...previous.filter(value => value.intent.source_id !== source.id), offer]);
  }

  async function runQuery(requestedQuery: TireQuery, requestedFilters: readonly TireFilter[], requestedSources: Source[]) {
    activeQuery.current?.controller.abort(); evidenceController.current?.abort(); setLocalOffers([]);
    const currentGeneration = ++generation.current;
    const controller = new AbortController();
    const query = Object.freeze({ ...requestedQuery });
    const filters = Object.freeze(requestedFilters.map(filter => Object.freeze({ ...filter })));
    const context: ActiveQuery = { query, filters, sources: [...requestedSources],
      accessGenerations: Object.fromEntries(requestedSources.map(source => [source.id, sourceAccess.get(source.id)?.management.access_generation ?? -1])),
      fallbackEligible: Object.fromEntries(requestedSources.map(source => [source.id, canQuerySource(sourceAccess.get(source.id), true) && canFetchSource(sourceAccess.get(source.id), true)])),
      attempts: Object.fromEntries(requestedSources.map(source => [source.id, crypto.randomUUID()])), fallbackGeneration: ++fallbackGeneration.current, fallbackDraft: currentDraftKey.current, generation: currentGeneration, controller };
    activeQuery.current = context;
    setSubmittedLabel([query.size, query.model].filter(Boolean).join(" · "));
    setSubmittedFilterLabels(filters.map(filter => describeFilter(filter, filterCatalog)));
    setNotice(""); setEvidence(null); setEvidenceError(""); setEvidenceLoading(false); setSelectedSnapshot("");
    setRuns(requestedSources.map(source => ({ source, loading: true }))); setVisibleCounts({});
    let directoryFailure: unknown;
    const latest = await refreshSources(cause => { directoryFailure = cause; });
    if (controller.signal.aborted || currentGeneration !== generation.current) return;
    if (!latest || requestedSources.some(source => !sourceAccess.canQuery(source.id) || context.accessGenerations[source.id] !== sourceAccess.get(source.id)?.management.access_generation)) {
      setNotice("来源目录待核对或所选来源状态已变化，未发起新的在线查询。历史库仍可独立查看。");
      setRuns(requestedSources.map(source => ({ source, loading: false, error: directoryFailure ? errorText(directoryFailure) : "来源目录待核对或许可已变化。" })));
      if (!latest && directoryFailure) await Promise.allSettled(requestedSources.map(source => offerDeviceFallback(context, source, directoryFailure)));
      return;
    }
    await Promise.allSettled(requestedSources.map(async source => {
      try {
        const data = await tireApi.liveQuery(source.id, query, controller.signal, undefined, filters);
        if (!controller.signal.aborted) { updateRun(source.id, currentGeneration, { data, loading: false }); await offerDeviceFallback(context, source, data); }
      } catch (error) { if (!isAbort(error) && !controller.signal.aborted) { updateRun(source.id, currentGeneration, { error: errorText(error), loading: false }); await offerDeviceFallback(context, source, error); } }
    }));
  }

  async function decideFallback(run: SourceRun, decision: "allow" | "deny") {
    const context = activeQuery.current;
    if (!context || !run.data || run.consentPending || context.controller.signal.aborted) return;
    setLocalOffers(previous => previous.filter(value => value.intent.source_id !== run.source.id));
    updateRun(run.source.id, context.generation, { consentPending: true, error: undefined });
    try {
      if (!await sourceAccess.ensure(run.source.id, "management") || context.controller.signal.aborted || context.accessGenerations[run.source.id] !== sourceAccess.get(run.source.id)?.management.access_generation) { updateRun(run.source.id, context.generation, { consentPending: false, error: "来源许可待核对或已变化，未使用旧授权。" }); return; }
      const consent = await tireApi.consent(run.data.query_id, decision, context.controller.signal);
      if (generation.current !== context.generation || context.controller.signal.aborted) return;
      if (decision === "deny") updateRun(run.source.id, context.generation, { denied: true, consentPending: false });
      else {
        const data = await tireApi.liveQuery(run.source.id, context.query, context.controller.signal, consent.id, context.filters);
        if (!context.controller.signal.aborted) updateRun(run.source.id, context.generation, { data, consentPending: false });
      }
    } catch (error) { if (!isAbort(error)) updateRun(run.source.id, context.generation, { error: errorText(error), consentPending: false }); }
  }

  function clearEvidence() {
    evidenceController.current?.abort(); setEvidence(null); setEvidenceError(""); setEvidenceLoading(false); setSelectedSnapshot("");
  }

  async function showEvidence(snapshotId: string, kind: "tire" | "vehicle" = "tire") {
    evidenceReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    evidenceController.current?.abort();
    const controller = new AbortController(); evidenceController.current = controller;
    setSelectedSnapshot(snapshotId); setEvidenceKind(kind); setEvidence(null); setEvidenceLoading(true); setEvidenceError("");
    if (window.innerWidth < 1180) requestAnimationFrame(() => evidencePanel.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    try { const data = await (kind === "vehicle" ? tireApi.vehicleEvidence(snapshotId, controller.signal) : tireApi.evidence(snapshotId, controller.signal)); if (!controller.signal.aborted) setEvidence(data); }
    catch (error) { if (!controller.signal.aborted && !isAbort(error)) setEvidenceError(errorText(error)); }
    finally { if (!controller.signal.aborted) setEvidenceLoading(false); }
  }

  function toggleCompare(variant: Variant) {
    setCompared(previous => {
      if (previous.some(item => item.id === variant.id)) return previous.filter(item => item.id !== variant.id);
      if (previous.length >= 4 || variant.lifecycle?.state === "revoked") return previous;
      return [...previous, variant];
    });
  }

  async function toggleWatch(variant: Variant) {
    if (watchLock.current.has(variant.id)) return;
    watchLock.current.add(variant.id); setPendingWatch(previous => [...previous, variant.id]);
    try {
      const existing = watches.find(item => item.variant_id === variant.id);
      if (existing) { await tireApi.unwatch(existing.id); setWatches(previous => previous.filter(item => item.id !== existing.id)); setNotice("已取消关注。"); }
      else { const added = await tireApi.watch(variant.id); setWatches(previous => [...previous.filter(item => item.variant_id !== variant.id), { ...added, variant: added.variant || variant }]); setNotice("已加入关注。可在我的关注中单独创建监控规则。"); }
    } catch (error) { setNotice(errorText(error)); }
    finally { watchLock.current.delete(variant.id); setPendingWatch(previous => previous.filter(id => id !== variant.id)); }
  }

  function identitySaved(review: IdentityReview) {
    const update = (variant: Variant) => variant.id === review.source.id ? { ...variant, identity_resolution: review.resolution } : variant;
    setRuns(previous => previous.map(run => run.data ? { ...run, data: { ...run.data, variants: run.data.variants.map(update) } } : run));
    setWatches(previous => previous.map(item => item.variant ? { ...item, variant: update(item.variant) } : item));
    setCompared(previous => previous.map(update));
    setComparisonRevision(value => value + 1);
  }

  function lifecycleSaved(review: LifecycleReview) {
    setLatestLifecycleReview(review);
    const update = (variant: Variant) => variant.id === review.variant_id ? { ...variant, lifecycle: review.lifecycle } : variant;
    setRuns(previous => previous.map(run => run.data ? { ...run, data: { ...run.data, variants: run.data.variants.map(update) } } : run));
    setWatches(previous => previous.map(item => item.variant ? { ...item, variant: update(item.variant) } : item));
    setCompared(previous => previous.map(update));
    setComparison(previous => previous.map(update).filter(row => row.lifecycle?.state !== "revoked"));
    setComparisonRevision(value => value + 1);
  }

  const variantActions = (variant: Variant, sourceId?: string) => ({
    compared: compared.some(item => item.id === variant.id), compareFull: compared.length >= 4,
    watched: watches.some(item => item.variant_id === variant.id), watchPending: pendingWatch.includes(variant.id),
    onCompare: () => toggleCompare(variant), onWatch: () => void toggleWatch(variant), onEvidence: () => void showEvidence(variant.snapshot_id),
    onCandidateEvidence: (snapshotId: string) => void showEvidence(snapshotId),
    onReview: () => setReviewTarget({ variant, sourceId }),
    onLifecycle: () => setLifecycleTarget(variant.id),
    onGarage: () => setGarageTire(variant),
    onAI: () => { setAiTarget({ variant, sourceId }); setAiOpen(true); },
  });
  const loading = runs.some(run => run.loading);
  const currentNav = navigation.find(item => item.id === view)!;
  const resultsCount = runs.reduce((total, run) => total + (hasQueryData(run.data) ? run.data!.variants.length : 0), 0);
  const availableModels = [...new Set(sources.filter(isQueryableSource).flatMap(source => source.supported_models || ["Pilot Sport EV", "Pilot Sport 4 S"]))];
  const regions = [...new Set(sources.map(source => source.region))];

  function chooseModel(value: string) {
    setModel(value);
    setSelectedSources(sources.filter(source => isQueryableSource(source) && supportsModel(source, value)).map(source => source.id));
  }

  function prefillVehicleSize(axleSize: string, context: string) {
    activeQuery.current?.controller.abort(); activeQuery.current = null; generation.current++;
    clearEvidence(); setSize(axleSize); setModel(""); setRegion(""); setSelectedSources([]); setRuns([]); setVisibleCounts({});
    setView("query"); setNotice(`已填入 ${context} 的尺寸 ${axleSize}。请自行选择来源地区和轮胎型号；此操作不匹配产品代码或原配 SKU。`);
    requestAnimationFrame(() => { searchInput.current?.focus(); window.scrollTo({ top: 0, behavior: "smooth" }); });
  }

  return <div className="app-shell" data-theme={theme}>
    <a className="skip-link" href="#main-content">跳转到主要内容</a>
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="胎迹首页"><span className="brand-symbol"><span /><span /><span /></span><span><strong>胎迹<span className="brand-period">.</span></strong><small>TIRE INTELLIGENCE</small></span></a>
      <div className="workspace-label"><span className="status-dot" />研究工作台 <span className="mono">01</span></div>
      <nav className="main-nav" aria-label="主导航">{navigation.map(item => <button type="button" key={item.id} className={view === item.id ? "nav-item active" : "nav-item"} aria-current={view === item.id ? "page" : undefined} onClick={() => setView(item.id)}><Icon name={item.icon} /><span>{item.label}<small>{item.english}</small></span>{item.id === "compare" && compared.length > 0 ? <b className="nav-count">{compared.length}</b> : null}</button>)}</nav>
      <div className="sidebar-bottom"><OfflineLibraryEntry platform={platform} className="future-note text-button" /><DeviceAiEntry platform={platform} className="future-note text-button" /><div className="phase-note"><span className="eyebrow">BUILD IN PROGRESS</span><p>每一个参数，<br />都应该有据可查。</p><span className="phase-label">数据 PoC · 本地工作区</span></div><button type="button" className="future-note text-button" onClick={() => setKnowledgeOpen(true)}><span>历史证据检索</span><span className="tag quiet">知识库</span></button><button type="button" className="future-note text-button" onClick={() => { setAiTarget(null); setAiOpen(true); }}><span>AI 知识应用</span><span className="tag quiet">证据分析</span></button><button type="button" className="future-note text-button" onClick={() => { setReportId(undefined); setReportsOpen(true); }}><span>证据报告库</span><span className="tag quiet">历史报告</span></button><div className="sidebar-foot"><span className="avatar">研</span><span>个人研究空间<small>当前无云端账户同步</small></span></div></div>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumb"><span>工作台</span><Icon name="chevron" size={12} /><strong>{currentNav.label}</strong></div><div className="topbar-actions">{platform.kind === "web" ? <OfflineLibraryEntry platform={platform} className="text-button mobile-offline-entry" /> : null}<span className={`connection ${health ? "connected" : ""}`}><span className="status-dot" />{booting ? "连接中" : health ? "API 已连接" : "API 未连接"}</span><button type="button" className="icon-button theme-toggle" onClick={toggleTheme} aria-label={theme === "light" ? "切换深色主题" : "切换浅色主题"}><Icon name={theme === "light" ? "moon" : "sun"} /></button></div></header>
      <div className="workbench-grid">
        <main id="main-content" className="main-content">
          {!booting && !sourceAccess.fresh ? <div className="source-access-notice" role="status">{sourceAccess.loading ? "正在核对来源目录，暂不发起新的在线操作。" : "来源目录刷新未完成，暂不发起新的在线操作。"} 历史证据与已保存记录仍可读取。<button type="button" className="text-button" disabled={sourceAccess.loading} onClick={() => void refreshSources()}>刷新来源目录</button></div> : null}
          {pwa ? <PwaStatus /> : null}
          <div className="page-heading"><div><span className="eyebrow">{view === "query" ? "FIND THE EXACT TIRE" : currentNav.english}</span><h1>{view === "query" ? <>从规格出发<span className="accent">，</span>让证据说话<span className="accent">。</span></> : currentNav.label}</h1><p>{view === "query" ? "精确到每一个 SKU，追溯每一项参数的原始来源。" : view === "vehicles" ? "按准确代际与官方配置，分别核对版本、轮毂和前后轴。" : view === "garage" ? "保存车辆、配置与前后轴，分别记录当前使用的精确轮胎。" : view === "compare" ? "并排核对精确规格；跨测试场次的成绩不直接排名。" : view === "watch" ? "保存需要持续研究的轮胎，查看已记录的变化。" : "了解来源的接入状态，检查原始记录与解析版本。"}</p></div><span className="section-number" aria-hidden="true">0{navigation.findIndex(item => item.id === view) + 1}</span></div>
          {notice ? <div className="notice" role="status"><Icon name="file" size={17} /><span>{notice}</span><button className="icon-button" aria-label="关闭提示" onClick={() => setNotice("")}><Icon name="close" size={16} /></button></div> : null}

          {view === "query" ? <>
            <form className="query-panel" onSubmit={submitQuery}>
              <div className="panel-title"><span><Icon name="search" size={18} />在线查询</span><kbd>Ctrl / ⌘ K</kbd></div>
              <div className="query-fields"><label className="size-field"><span>轮胎尺寸</span><div className="input-wrap"><input ref={searchInput} value={size} onChange={event => setSize(event.target.value)} placeholder="例如 225/45 R18" maxLength={40} autoComplete="off" spellCheck={false} aria-describedby="size-hint" /><span className="input-unit">SIZE</span></div></label><label className="model-field"><span>轮胎型号 <small>当前支持</small></span><select value={model} onChange={event => chooseModel(event.target.value)}>{!model ? <option value="" disabled>请选择轮胎型号</option> : !availableModels.includes(model) ? <option value={model} disabled>{model} · {booting ? "等待来源目录" : "当前来源未接入，请重新选择"}</option> : null}{availableModels.filter(Boolean).map(value => <option key={value} value={value}>{value}</option>)}</select></label><button type="submit" className="primary-button query-submit" disabled={booting || !sourceAccess.items.length || !sources.some(source => isQueryableSource(source) && supportsModel(source, model) && selectedSources.includes(source.id) && (region === "all" || source.region === region))}><span>{loading ? "重新查询" : "查询轮胎"}</span><Icon name="arrow" size={18} /></button></div>
              <div id="size-hint" className="input-hint">按来源已接入的型号与地区在线查询。不同地区、OE 与技术配置独立保留，相同尺寸不代表同一 SKU。</div>
              <div className="region-selector"><label>来源地区<select value={region} onChange={event => setRegion(event.target.value)}>{!region ? <option value="" disabled>请选择来源地区</option> : null}<option value="all">全部地区 · 分别保留区域版本</option>{regions.map(value => <option value={value} key={value}>{regionLabels[value] || value}</option>)}</select></label></div><div className="source-selector"><span className="field-caption">查询来源</span>{booting ? <span className="muted">正在加载来源…</span> : sources.length ? sources.filter(source => source.target_kind !== "recall" && (region === "all" || source.region === region)).map(source => <label className={`source-option${isQueryableSource(source) && supportsModel(source, model) ? "" : " unavailable"}`} key={source.id}><input type="checkbox" disabled={!sourceAccess.fresh || !isQueryableSource(source) || !supportsModel(source, model)} checked={isQueryableSource(source) && supportsModel(source, model) && selectedSources.includes(source.id)} onChange={() => setSelectedSources(previous => previous.includes(source.id) ? previous.filter(id => id !== source.id) : [...previous, source.id])} /><span>{source.name}<small>{source.region}</small>{!isQueryableSource(source) || !supportsModel(source, model) ? <small className="source-availability">{!isQueryableSource(source) ? statusLabels[source.status] || source.status : "未接入此型号"}</small> : null}</span></label>) : <span className="muted">没有可用来源配置</span>}</div>
              {sourceError ? <div className="inline-error" role="alert">无法加载来源：{sourceError}<button type="button" className="text-button" onClick={() => void loadInitial(new AbortController().signal)}>重新连接</button></div> : null}
              <QueryFilters drafts={filterDrafts} catalog={filterCatalog} loading={filterCatalogLoading} error={filterCatalogError} validationError={filterValidationError} onChange={next => { setFilterDrafts(next); setFilterValidationError(""); }} onRetry={() => setFilterCatalogRevision(value => value + 1)} />
              <div className="query-policy"><Icon name="shield" size={14} /><span>优先在线核验 · 历史读取遵循独立策略与本次消费回执</span></div>
            </form>
            <QueryFallbackPolicy kind="tire" sourceIds={selectedSources} sessionReady={!booting} />

            <div className="results-heading"><h2>{runs.length ? "查询记录" : "开始你的第一次查询"}</h2><span className="mono">{runs.length ? `${runs.some(run => hasQueryData(run.data)) ? `${resultsCount} MATCHED SKU` : "等待可核验结果"} / ${runs.length} SOURCES` : "LIVE FIRST / EVIDENCE ALWAYS"}</span></div>
            {runs.length ? <section className="query-submitted-selection" aria-label="本次已提交筛选条件"><div><strong>本次已提交条件 · 全部满足</strong><button type="button" className="text-button" onClick={() => { const context = activeQuery.current; if (context) void runQuery(context.query, context.filters, context.sources); }}>按本次条件重新在线查询</button></div>{submittedFilterLabels.length ? <ul>{submittedFilterLabels.map((label, index) => <li key={`${index}-${label}`}>{label}</li>)}</ul> : <p>未添加规格筛选条件，展示本次型号、尺寸与来源范围内的全部返回规格。</p>}<p>上方为查询草稿；删除或修改条件后需点击「查询轮胎」提交。此处保留已提交的条件。</p></section> : null}
            {platform.offline && localOffers.length ? <div className="local-fallback-list" aria-label="本次独立设备历史授权">{localOffers.map(offer => <LocalFallbackPanel key={offer.intent.attempt_id} offer={offer} storage={platform.offline!} onClose={() => setLocalOffers(previous => previous.filter(value => value.intent.attempt_id !== offer.intent.attempt_id))} />)}</div> : null}
            {runs.length ? <div className="results-list" aria-live="polite">{runs.map(run => <section key={run.source.id} className="source-result"><div className="source-result-heading"><div><span className="source-monogram">{run.source.name.slice(0, 1)}</span><div><h3>{run.source.name}</h3><small>{run.source.region} · {submittedLabel}</small></div></div><span className={`tag ${run.data?.data_state === "live" || run.data?.data_state === "live_verified_304" ? "success" : run.data?.data_state === "local_snapshot" ? "warning" : "quiet"}`}>{run.loading ? "在线查询中…" : run.denied ? "已拒绝本地回退" : run.data ? stateLabels[run.data.data_state] : "请求失败"}</span></div>
              {run.loading ? <div className="run-loading"><span className="spinner" />正在请求来源，获取可核验的规格与证据…</div> : null}
              {run.error ? <div className="inline-error" role="alert">{run.error}</div> : null}
              {run.data?.data_state === "consent_required" && !run.denied ? <div className="consent-card"><div className="consent-symbol"><Icon name="shield" size={22} /></div><div><h4>在线查询未完成，是否查看本地快照？</h4><SourceReason reason={run.data.reason} /><p>仅授权「{submittedLabel}」及本次已提交的 {submittedFilterLabels.length} 项筛选条件，在 {run.source.name} 的这一次查询。编辑草稿不会改变此次授权；历史数据可能已变化。</p><div className="consent-actions"><button className="primary-button compact" disabled={run.consentPending} onClick={() => void decideFallback(run, "allow")}>{run.consentPending ? "处理中…" : "仅本次允许"}</button><button className="secondary-button compact" disabled={run.consentPending} onClick={() => void decideFallback(run, "deny")}>拒绝，保持无结果</button></div></div></div> : null}
              {run.denied ? <div className="result-explanation">已拒绝本次回退。没有读取本地参数；你可以重新发起在线查询。</div> : null}
              {run.data?.data_state === "source_unavailable" ? <div className="result-explanation"><SourceReason reason={run.data.reason} /></div> : null}
              {run.data?.data_state === "local_snapshot" ? <div className="snapshot-banner"><strong>历史快照 · 非实时数据</strong><span>原观察时间：{formatTime(run.data.snapshot_observed_at)}</span><span className="mono">consent_id: {run.data.consent_id || "未提供"}</span></div> : null}
              {hasQueryData(run.data) && run.data?.selection ? <QuerySelectionCounts selection={run.data.selection} local={run.data.data_state === "local_snapshot"} /> : null}
              {run.data?.verified_at ? <div className="verification-line">在线验证时间：{formatTime(run.data.verified_at)}</div> : null}
              {hasQueryData(run.data) ? run.data?.variants.slice(0, visibleCounts[run.source.id] || 20).map(variant => <VariantCard key={variant.id} variant={variant} {...variantActions(variant, run.source.id)} selected={evidenceKind === "tire" && selectedSnapshot === variant.snapshot_id} />) : null}
              {hasQueryData(run.data) && run.data && run.data.variants.length > 20 ? <div className="result-pagination"><span>已显示 {Math.min(visibleCounts[run.source.id] || 20, run.data.variants.length)} / {run.data.variants.length} 项匹配规格</span>{(visibleCounts[run.source.id] || 20) < run.data.variants.length ? <button className="secondary-button" onClick={() => setVisibleCounts(previous => ({ ...previous, [run.source.id]: (previous[run.source.id] || 20) + 20 }))}>再显示 {Math.min(20, run.data.variants.length - (visibleCounts[run.source.id] || 20))} 项 · 余 {run.data.variants.length - (visibleCounts[run.source.id] || 20)} 项</button> : <span>已显示全部</span>}</div> : null}
              {hasQueryData(run.data) && run.data && !run.data.variants.length ? <div className="result-explanation">{submittedFilterLabels.length ? "本次来源返回范围内，没有可确认满足全部条件的规格。未能判定的规格不计入匹配；可删除或调整单项条件后重新在线查询。这不代表官网完整目录为空。" : run.data.data_state === "local_snapshot" ? "本地未找到符合本次查询的历史规格。" : "来源未返回匹配的精确规格。可调整尺寸或型号后重试。"}</div> : null}
              {hasQueryData(run.data) && run.data?.provenance.length ? <div className="provenance-list">{run.data.provenance.map(item => <button className="evidence-link" key={item.snapshot_id} onClick={() => void showEvidence(item.snapshot_id)}><Icon name="file" size={14} /><span>查看来源证据</span><small>{item.parser_version}</small><Icon name="chevron" size={12} /></button>)}</div> : null}
              {hasQueryData(run.data) && run.data?.conflicts.length ? <details className="conflict-details"><summary>当前来源快照有 {run.data.conflicts.length} 项字段冲突，未自动裁定</summary><ConflictDetails conflicts={asConflicts(run.data.conflicts).slice(0, 20)} />{run.data.conflicts.length > 20 ? <p>此处先展示 20 项，请在对应规格卡片与原始证据中继续核对。</p> : null}</details> : null}
            </section>)}</div> : <section className="empty-query"><div className="empty-illustration"><TireDrawing /></div><h3>规格清晰，选择才有依据</h3><p>输入尺寸并选择型号，从可信来源查找轮胎。<br />产品代码、区域与技术配置会被分别保留。</p><div className="example-queries"><span>试试尺寸</span>{["245/40 R20", "265/40 R20", "255/45 R19"].map(example => <button type="button" key={example} onClick={() => { setSize(example); searchInput.current?.focus(); }}>{example}<Icon name="arrow" size={13} /></button>)}</div><div className="empty-footnote"><span className="tiny-square" />此处尚无查询结果，示例仅填入查询条件。</div></section>}
            <div className="principles-row"><div><span>01</span><strong>精确识别</strong><p>不把同名轮胎合并成同一规格</p></div><div><span>02</span><strong>来源可追溯</strong><p>保留原始快照与解析版本</p></div><div><span>03</span><strong>新旧有界</strong><p>明确区分在线数据与历史记录</p></div></div>
          </> : null}

          {view === "vehicles" ? <VehicleFitments sessionReady={!booting} onEvidence={id => void showEvidence(id, "vehicle")} onTireEvidence={id => void showEvidence(id, "tire")} onClearEvidence={clearEvidence} onQuerySize={prefillVehicleSize} onSaveToGarage={(snapshotId, fitmentId, label) => setGarageFitment({ snapshotId, fitmentId, label })} renderReason={reason => <SourceReason reason={reason} />} /> : null}

          {view === "garage" ? <GarageWorkspace lifecycleReview={latestLifecycleReview} sessionReady={!booting} onQuerySize={prefillVehicleSize} onVehicleEvidence={id => void showEvidence(id, "vehicle")} onVariant={id => setLifecycleTarget(id)} /> : null}
          {view === "compare" ? <div className="compare-toolbar report-entry"><p>报告固定保存已经预览的证据与分析，打开和导出均不调用模型。</p><button type="button" className="secondary-button" onClick={() => { setReportId(undefined); setReportsOpen(true); }}>打开证据报告库</button></div> : null}
          {view === "compare" ? <section className="comparison-section"><div className="panel-title"><span>已选规格 <b className="count-badge">{compared.length} / 4</b></span>{compared.length ? <div className="compare-toolbar"><button className="text-button" disabled={comparisonLoading} onClick={() => setComparisonRevision(value => value + 1)}>重新核对记录</button><button className="secondary-button compact" disabled={comparisonLoading || !!comparisonError || !comparison.length || !comparisonFingerprint} onClick={() => setSavingSelection({ variant_ids: compared.map(item => item.id), include_manual: includeManual, resolve_identities: resolveIdentities, expected_fingerprint: comparisonFingerprint })}>保存本次比较</button><button className="secondary-button compact" disabled={comparisonLoading || !!comparisonError || !comparison.length} onClick={() => { setAiTarget({ references: comparison.map(v => ({ kind: "tire", snapshot_id: v.snapshot_id, variant_id: v.id })), label: "所选规格的来源历史证据（不含人工覆盖值）" }); setAiOpen(true); }}>AI 解释所选来源规格</button><button className="text-button" onClick={() => setCompared([])}>清空选择</button></div> : null}</div>{compared.length ? <><div className="compare-selections">{compared.map(item => <button key={item.id} className="compare-chip" onClick={() => toggleCompare(item)}>{item.brand} {item.model} · {item.size}<Icon name="close" size={15} /></button>)}</div><div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 历史规格比较</strong><span>比较基于已保存的来源快照，不代表当前在线参数；点击证据查看记录时间。</span></div><label className="review-checkbox compare-review-toggle"><input type="checkbox" checked={includeManual} onChange={event => setIncludeManual(event.target.checked)} />包含已核验的人工修订（保留来源值，待复核的不应用）</label><label className="review-checkbox compare-review-toggle"><input type="checkbox" checked={resolveIdentities} onChange={event => setResolveIdentities(event.target.checked)} />采用已核对的身份更正与合并（有效合并保留本次已选双方证据；身份更正只取目标，重复目标合为一列）</label>{!comparisonLoading && identityMappings.some(item => item.requested_id !== item.resolved_id) ? <section className="review-boundary" aria-label="本次身份映射"><strong>本次明确采用的身份映射</strong>{identityMappings.filter(item => item.requested_id !== item.resolved_id).map(item => <p key={item.requested_id}><code>{item.requested_id}</code> → <code>{item.resolved_id}</code> · 修订{item.revision}<button type="button" className="text-button" onClick={() => setIdentityTarget(item.requested_id)}>核对身份决定</button></p>)}<p>当前比较 {comparison.length} 个独立目标；原选择与目标映射会一同保存。</p></section> : null}{comparisonLoading ? <div className="run-loading"><span className="spinner" />正在读取所选规格…</div> : comparisonError ? <div className="inline-error" role="alert">{comparisonError}</div> : <>{excludedVariants.length ? <section className="source-conflict" aria-label="已排除的撤销版本"><strong>已撤销版本不参与比较</strong>{excludedVariants.map(item => <p key={item.id}>{item.brand} {item.model} · {item.size} · {item.manufacturer_product_code || "代码未知"}<button type="button" className="text-button" onClick={() => setLifecycleTarget(item.id)}>查看版本状态</button></p>)}</section> : null}{comparison.length ? <ComparisonTable variants={comparison} onEvidence={id => void showEvidence(id)} /> : <p className="muted padded">当前没有可参与比较的规格，请核对撤销状态或选择其他版本。</p>}</>}</> : <div className="quality-empty"><p>在查询结果中选择最多 4 个精确 SKU，创建新的比较；已有记录可在下方打开。</p><button className="secondary-button" onClick={() => setView("query")}>前往查询</button></div>}</section> : null}

          {view === "compare" && comparisonConflicts.length ? <section className="source-conflict" aria-label="本次比较的来源字段冲突"><strong>本次比较的来源字段冲突 · 默认值不代表裁定</strong><ConflictDetails conflicts={comparisonConflicts} /></section> : null}
          {view === "compare" ? <SavedComparisonsPanel sessionReady={!booting} refreshVersion={savedComparisonsRevision} renderComparison={(variants, onEvidence, conflicts) => <><ComparisonTable variants={variants} onEvidence={onEvidence} historical />{conflicts.length ? <section className="source-conflict" aria-label="保存时的来源字段冲突"><strong>保存时的来源字段冲突 · 未自动裁定</strong><ConflictDetails conflicts={conflicts} /></section> : null}</>} /> : null}
          {view === "watch" ? <><section className="watch-section"><div className="panel-title"><span>关注规格 <b className="count-badge">{watches.length}</b></span><span className="tag quiet">关注标记与监控规则分别保存</span></div>{watchLoading ? <div className="run-loading"><span className="spinner" />正在加载关注记录…</div> : watchError ? <div className="inline-error" role="alert">{watchError}</div> : watches.length ? <><div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 已保存规格</strong><span>关注列表展示历史记录，不代表当前在线参数。</span></div>{watches.map(item => item.variant ? <div key={item.id}>{item.tracking_state === "identity_review_required" ? <p className="review-warning">此关注仍指向旧 SKU；身份需核对，未自动迁移到相关候选。</p> : null}<VariantCard variant={item.variant} {...variantActions(item.variant)} selected={evidenceKind === "tire" && selectedSnapshot === item.variant.snapshot_id} /></div> : <div className="result-explanation" key={item.id}>规格 {item.variant_id} 的详情不可用。</div>)}</> : <EmptyPanel icon="bookmark" title="为下一次研究留个标记" description="在查询结果中关注精确规格，便于稍后返回核对。" action={() => setView("query")} actionText="查找轮胎" />}</section><section className="changes-section"><div className="panel-title"><span>已记录的变更</span></div>{changesError ? <div className="inline-error" role="alert">{changesError}</div> : changes.length ? changes.map(change => <details key={change.id}><summary>{change.kind || change.field || "规格变更"} · {formatTime(change.observed_at)}</summary><pre>{JSON.stringify(change, null, 2)}</pre></details>) : <p className="muted padded">暂无变更记录。可在下方创建规则，查看符合条件的站内提醒。</p>}</section><MonitoringCenter sources={sources} watches={watches} onEvidence={id => void showEvidence(id)} onExplain={notice => { setAiTarget({ references: [{ kind: "change_event", change_id: notice.change_id }], label: `${notice.rule_name} · 这次历史变化`, defaultQuestion: "这次已记录的变化具体发生了什么？哪些内容值得关注，证据有哪些限制？请区分来源事实与推断，只解释这些冻结记录，不把首次观察称为新发布。" }); setAiOpen(true); }} /></> : null}

          {view === "compare" ? <div className="ai-entry compare-toolbar"><button className="secondary-button" onClick={() => setKnowledgeOpen(true)}>检索历史证据</button><button className="secondary-button" onClick={() => { setAiTarget(null); setAiOpen(true); }}>AI 调用记录与配置</button></div> : null}
          {view === "compare" ? <TestEvents sessionReady={!booting} /> : null}
          {view === "sources" ? <><section className="quarantine-panel"><div className="panel-title"><span>轮胎安全召回</span><button type="button" data-recall-entry className="secondary-button" disabled={booting} onClick={() => setRecallsOpen(true)}>查询与监控召回公告</button></div><p className="quality-intro">NHTSA 美国监管公告 · 在线检索候选，核对官方范围与补救措施。</p></section><SourceManagement /><MonitorTaskCenter /><SourceQuality sources={sources} sessionReady={!booting} /><div className="method-note"><Icon name="shield" size={24} /><div><h3>证据保留原貌，事实保留版本</h3><p>每份快照记录来源 URL、观察时间、解析器版本和 SHA-256。选择查询结果中的「查看证据」，即可在右侧核对原始内容。</p><p>远端页面只作为纯文本证据展示，不执行其中的脚本或指令。</p></div></div></> : null}

          {savingSelection ? <SaveComparisonDialog selection={savingSelection} onClose={() => setSavingSelection(null)} onRefresh={() => { setSavingSelection(null); setComparisonRevision(value => value + 1); }} onSaved={() => { setSavingSelection(null); setSavedComparisonsRevision(value => value + 1); setNotice("已固定保存本次比较与引用证据。"); }} /> : null}
          {garageTire ? <AssignTireDialog variant={garageTire} onClose={() => setGarageTire(null)} onSaved={() => { setGarageTire(null); setView("garage"); setNotice("已保存当前轮胎记录，请核对前后轴。"); }} /> : null}
          {garageFitment ? <SaveFitmentDialog {...garageFitment} onClose={() => setGarageFitment(null)} onSaved={() => { setGarageFitment(null); setView("garage"); setNotice("已保存所选配置，尚未指定当前轮胎。"); }} /> : null}
          {lifecycleTarget ? <VariantLifecycleDialog key={lifecycleTarget} variantId={lifecycleTarget} onClose={() => setLifecycleTarget("")} onSaved={lifecycleSaved} onIdentity={() => { setIdentityTarget(lifecycleTarget); setLifecycleTarget(""); }} /> : null}
          {identityTarget ? <IdentityReviewDialog key={identityTarget} variantId={identityTarget} onClose={() => { setLifecycleTarget(identityTarget); setIdentityTarget(""); }} onSaved={identitySaved} /> : null}
          {reviewTarget ? <FactReviewDialog key={`${reviewTarget.variant.id}:${reviewTarget.sourceId || ""}`} {...reviewTarget} onClose={() => setReviewTarget(null)} onSaved={() => setComparisonRevision(value => value + 1)} /> : null}
          {knowledgeOpen ? <KnowledgeSearchDialog onOffline={references => setOfflineReferences(references)} onClose={() => setKnowledgeOpen(false)} onAnalyze={references => { setAiTarget({ references, label: "从知识检索选择的历史证据", defaultQuestion: references.some(reference => reference.kind === "recall") ? "整理所选证据中的原始事实、公告措施及局限；不判断具体轮胎适用性。" : undefined }); setAiOpen(true); }} onLiveQuery={recall => { setKnowledgeOpen(false); if (recall) { setRecallCampaign(recall.campaign_number); setRecallsOpen(true); } else { setView("query"); requestAnimationFrame(() => searchInput.current?.focus()); } }} /> : null}
          {offlineReferences ? <OfflineLibraryDialog platform={platform} references={offlineReferences} onClose={() => setOfflineReferences(null)} /> : null}
          {aiOpen ? <AIAnalysisDialog target={aiTarget || undefined} onClose={() => setAiOpen(false)} onOpenReport={id => { setAiOpen(false); setReportId(id); setReportsOpen(true); }} /> : null}
          {reportsOpen ? <ReportsDialog initialId={reportId} onClose={() => setReportsOpen(false)} /> : null}
          <footer className="content-footer"><span>胎迹 · 轮胎情报工作台</span><span className="mono">DATA PoC / v0.1</span></footer>
        </main>

        <aside className="evidence-panel" ref={evidencePanel} aria-label="证据检查器"><div className="evidence-panel-heading"><span><Icon name="file" size={18} />证据检查器</span><span className="mono">TRACE</span></div>{evidenceLoading ? <div className="evidence-placeholder"><span className="spinner" /><h3>正在读取原始证据</h3><p>核对快照与来源信息…</p></div> : evidenceError ? <div className="inline-error" role="alert">{evidenceError}<button className="text-button" onClick={() => void showEvidence(selectedSnapshot, evidenceKind)}>重试</button></div> : evidence ? <EvidenceDetail evidence={evidence} kind={evidenceKind} /> : <><div className="evidence-placeholder"><span className="evidence-placeholder-icon"><Icon name="file" size={28} /><span className="evidence-cross">+</span></span><h3>把结论放回来源中</h3><p>选择一条轮胎规格或参数，<br />在这里检查它的原始证据。</p><div className="placeholder-lines"><span /><span /><span /></div></div><div className="evidence-guide"><span className="eyebrow">一条可信事实的来路</span><ol><li><span>1</span><div><strong>原始来源</strong><p>官网页面与公开数据记录</p></div></li><li><span>2</span><div><strong>不可覆盖的快照</strong><p>观察时间与内容校验值</p></div></li><li><span>3</span><div><strong>可追溯的规格</strong><p>精确 SKU 与解析版本</p></div></li></ol></div></>}<div className="evidence-policy"><span className="status-dot" /><span>没有来源，就不把参数当作事实。</span></div></aside>
      </div>
    </div>
    {compared.length && view === "query" ? <div className="comparison-tray"><Icon name="compare" size={18} /><span>已选 <strong>{compared.length}</strong> 项规格</span><button className="primary-button compact" onClick={() => setView("compare")}>查看比较<Icon name="arrow" size={15} /></button></div> : null}
    {recallsOpen ? <RecallDialog sessionReady={!booting} initialCampaign={recallCampaign} onAnalyze={target => { setAiTarget(target); setAiOpen(true); }} onClose={() => setRecallsOpen(false)} /> : null}
    <nav className="mobile-nav" aria-label="移动导航">{navigation.map(item => <button key={item.id} className={view === item.id ? "active" : ""} aria-current={view === item.id ? "page" : undefined} onClick={() => { setView(item.id); window.scrollTo({ top: 0, behavior: "smooth" }); }}><Icon name={item.icon} size={20} /><span>{item.label}</span></button>)}</nav>
  </div>;
}

function VariantFieldFacts({ variant, onEvidence, onCandidateEvidence }: { variant: Variant; onEvidence: () => void; onCandidateEvidence: (snapshotId: string) => void }) {
  const facts = visibleFacts(variant.facts || {}, variant.manufacturer_product_code);
  const fields = variant.field_resolution?.fields.filter(field => !field.identity_bound) || [];
  const rawFacts = facts.length ? <div className="fact-grid">{facts.map(([key, value]) => <button key={key} className="fact-button" onClick={onEvidence} title="核对保留的原来源快照"><span>{factLabels[key] || key}</span><strong>{formatFactValue(key, value)}</strong><Icon name="external" size={12} /></button>)}</div> : null;
  return <>{variant.field_resolution ? <>
    <p className="field-card-label">本次技术字段默认展示 · 身份字段保持原记录</p>
    <div className="field-card-defaults">{fields.map(field => <div key={field.field}><span>{field.label}</span><strong>{fieldDefaultText(field)}</strong>{field.state === "conflict_preferred" ? <small>仍有来源冲突</small> : null}</div>)}</div>
    <details className="field-card-evidence"><summary>核对本次默认值与全部字段来源</summary><FieldResolutionView resolution={variant.field_resolution} onEvidence={candidate => { if (candidate.snapshot_id) onCandidateEvidence(candidate.snapshot_id); }} /></details>
    <details className="field-card-raw"><summary>保留的原来源参数</summary><p>以下为此卡片原快照的参数，默认展示依据另见上方。</p>{rawFacts}</details>
  </> : <><p className="field-resolution-missing">此记录未保存字段权威依据，以下保留原来源参数。</p>{rawFacts}</>}</>;
}

function VariantCard({ variant, compared, compareFull, watched, watchPending, selected, onCompare, onWatch, onEvidence, onCandidateEvidence, onReview, onLifecycle, onGarage, onAI }: { variant: Variant; compared: boolean; compareFull: boolean; watched: boolean; watchPending: boolean; selected: boolean; onCompare: () => void; onWatch: () => void; onEvidence: () => void; onCandidateEvidence: (snapshotId: string) => void; onReview: () => void; onLifecycle: () => void; onGarage: () => void; onAI: () => void }) {
  const conflicts = variantConflicts(variant);
  const anomalies = variantAnomalies(variant);
  return <article className={`variant-card${selected ? " selected" : ""}`}><div className="variant-card-heading"><div><span className="variant-brand">{displayValue(variant.brand)} <small>{variant.region}</small></span><h3>{displayValue(variant.model)}</h3></div><button className={`icon-button bookmark-button${watched ? " checked" : ""}`} onClick={onWatch} disabled={watchPending} aria-label={watched ? `取消关注 ${variant.model}` : `关注 ${variant.model}`} aria-pressed={watched}><Icon name={watchPending ? "refresh" : "bookmark"} size={20} /></button></div><div className="variant-size"><strong>{variant.size}</strong><span>{displayValue(variant.load_index)} {displayValue(variant.speed_rating)}</span>{hasFieldConflict(variant, "xl") ? <span className="tag warning">XL 待核验</span> : variant.xl ? <span className="tag quiet">XL</span> : null}{variant.hl ? <span className="tag quiet">HL</span> : null}{variant.run_flat ? <span className="tag quiet">防爆</span> : null}{variant.oe_mark ? <span className="tag quiet">OE · {variant.oe_mark}</span> : null}</div>{variant.lifecycle?.state === "revoked" ? <div className="snapshot-banner"><strong>已撤销 · 本地版本管理</strong><span>{variant.lifecycle.reason}。下列参数保留来源原貌，此版本不参与比较。</span></div> : null}{conflicts.length ? <section className="source-conflict" aria-label="来源字段冲突"><strong>来源字段冲突 · 尚未裁定</strong><p>同一来源快照存在不同取值，相关规格保持待核验。</p><ConflictDetails conflicts={conflicts} /></section> : null}{anomalies.length ? <section className="source-conflict" aria-label="来源参数异常"><strong>来源参数异常 · 保留原文，未采纳为标准值</strong>{anomalies.map((item, index) => <p key={`${item.field}-${index}`}>{conflictFieldLabel(item.field)}：来源声明 {displayValue(item.raw_value)}。{item.reason === "source_temperature_outside_standard_enum" ? "耐热等级应为 A、B 或 C，当前 UTQG 三项均待核验。" : "请核对原始证据。"}</p>)}</section> : null}<dl className="variant-meta"><div><dt>产品代码</dt><dd className="mono">{displayValue(variant.manufacturer_product_code)}</dd></div><div><dt>静音技术</dt><dd>{displayValue(variant.acoustic_technology)}</dd></div></dl><IdentityContractBadge contract={variant.identity_contract} /><details className="identity-contract-details"><summary>核对身份合同与原记录边界</summary><p className="identity-contract-note">原快照身份规则：{variant.identity_contract_version || "记录时未注明"}；卡片原字段保留快照值。</p><IdentityContractEvidence contract={variant.identity_contract} /></details><VariantFieldFacts variant={variant} onEvidence={onEvidence} onCandidateEvidence={onCandidateEvidence} />{variant.identity_resolution ? <div className="review-boundary"><strong>{identityLabel(variant.identity_resolution.state)}</strong><p>卡片保留原始SKU与来源参数；采用身份修订前请进入版本状态核对。</p></div> : null}<div className="variant-actions"><button className="evidence-link" onClick={onEvidence}><Icon name="file" size={15} />查看证据<Icon name="chevron" size={12} /></button><button className="evidence-link review-link" onClick={onReview}>核验与纠错</button><button type="button" className="evidence-link" disabled={variant.lifecycle?.state === "revoked"} onClick={onAI}>AI 分析</button><button type="button" className="evidence-link" onClick={onLifecycle}>版本状态</button><button type="button" className="evidence-link" disabled={variant.lifecycle?.state === "revoked"} onClick={onGarage}>记入车库</button><button className={`secondary-button compact${compared ? " is-selected" : ""}`} onClick={onCompare} disabled={!compared && (compareFull || variant.lifecycle?.state === "revoked")} aria-pressed={compared}><Icon name={compared ? "check" : "compare"} size={15} />{compared ? "已加入比较" : variant.lifecycle?.state === "revoked" ? "已撤销，不参与比较" : compareFull ? "比较已达 4 项" : "加入比较"}</button></div></article>;
}

function EmptyPanel({ icon, title, description, action, actionText }: { icon: IconName; title: string; description: string; action: () => void; actionText: string }) {
  return <div className="empty-panel"><span className="empty-panel-icon"><Icon name={icon} size={30} /></span><h3>{title}</h3><p>{description}</p><button className="secondary-button" onClick={action}>{actionText}<Icon name="arrow" size={16} /></button></div>;
}

function ComparisonTable({ variants, onEvidence, historical = false }: { variants: Variant[]; onEvidence: (id: string) => void; historical?: boolean }) {
  const hasAuthority = variants.some(variant => variant.field_resolution);
  const rows: { label: string; value: (variant: Variant) => unknown }[] = [
    { label: "原记录身份规则", value: variant => variant.identity_contract_version || "记录时未注明" },
    { label: historical ? "保存时的身份合同" : "服务端现行身份合同", value: variant => identityContractText(variant.identity_contract, historical ? "saved" : "current") },
    { label: "合同中的产品代码", value: variant => variant.identity_contract?.current_identity?.manufacturer_product_code },
    { label: "本地身份核对", value: variant => variant.identity_resolution ? identityLabel(variant.identity_resolution.state) : "独立版本" },
    { label: "尺寸", value: variant => variant.size }, { label: "区域", value: variant => variant.region },
    { label: "产品代码", value: variant => variant.manufacturer_product_code }, { label: "载重指数", value: variant => variant.load_index },
    { label: "速度级别", value: variant => variant.speed_rating }, { label: "XL 加强型", value: variant => hasFieldConflict(variant, "xl") ? "来源冲突 · 待核验" : variant.xl },
    { label: "HL 高载重", value: variant => variant.hl }, { label: "原厂 OE 标记", value: variant => variant.oe_mark },
    { label: "静音技术", value: variant => variant.acoustic_technology }, { label: "防爆技术", value: variant => variant.run_flat },
  ];
  if (hasAuthority) {
    const decisions = [...new Map(variants.flatMap(variant => (variant.field_resolution?.fields || []).filter(field => !field.identity_bound).map(field => [field.field, field] as const))).values()];
    rows.push(...decisions.map(field => ({ label: `${field.label} · 来源默认`, value: (variant: Variant) => {
      const decision = variant.field_resolution?.fields.find(item => item.field === field.field);
      if (!decision) return variant.field_resolution ? "本次范围未包含此字段" : "此记录未保存字段权威依据";
      const selected = fieldDefaultText(decision);
      const curated = Object.entries(variant.curation?.fields || {}).find(([key]) => decision.candidates.some(candidate => candidate.source_id === variant.curation?.source_id && candidate.curation_field === key))?.[1];
      const manual = curated?.status === "manual_override" ? `；已选择人工值：${fieldValueText(curated.after.value)}（独立于来源默认）`
        : curated?.status === "revoked" ? "；人工核验视图已撤销此参数" : curated?.status === "needs_review" ? "；旧人工处理待复核，未应用" : "";
      return `${selected}${decision.state === "conflict_preferred" ? "（仍有来源冲突）" : ""}${manual}`;
    } })));
  } else {
    const factKeys = [...new Set(variants.flatMap(variant => visibleFacts({ ...variant.facts, ...variant.effective_facts }, variant.manufacturer_product_code).map(([key]) => key)))];
    rows.push(...factKeys.map(key => ({ label: factLabels[key] || key, value: (variant: Variant) => {
      const status = variant.curation?.fields[key]?.status;
      if (status === "revoked") return "已撤销（人工处理）";
      const value = formatFactValue(key, (key === "product_code_type" ? variant.facts : variant.effective_facts || variant.facts)?.[key]);
      return `${value}${status === "manual_override" ? "（人工纠错）" : status === "needs_review" ? "（旧人工处理待复核）" : ""}`;
    } })));
  }
  return <><p className="review-boundary">{hasAuthority ? "技术参数按本次字段规则展示来源默认值；没有默认值时保留未判定。身份行保留原记录，来源值、人工值与默认展示分别核对。" : "此记录未保存字段权威依据；下表保留原记录，不使用当前规则回填。"}</p>
    <div className="comparison-table-wrap" tabIndex={0} aria-label="规格对照表，可横向滚动"><table className="comparison-table"><thead><tr><th>规格字段</th>{variants.map(variant => <th key={variant.id}><small>{variant.brand}</small>{variant.model}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.label}><th scope="row">{row.label}</th>{variants.map(variant => <td key={variant.id}>{displayValue(row.value(variant))}</td>)}</tr>)}<tr><th scope="row">原始证据</th>{variants.map(variant => <td key={variant.id}><button className="evidence-link" onClick={() => onEvidence(variant.snapshot_id)}>查看快照<Icon name="external" size={12} /></button></td>)}</tr></tbody></table></div>
    <div className="comparison-field-evidence">{variants.map(variant => <details key={variant.id}><summary>{variant.model} · {variant.manufacturer_product_code || variant.id} · {historical ? "保存时" : "本次"}的全部字段来源</summary><FieldResolutionView resolution={variant.field_resolution} context={historical ? "saved" : "current"} onEvidence={candidate => { if (candidate.snapshot_id) onEvidence(candidate.snapshot_id); }} /><details className="field-reference"><summary>保留的原来源参数与独立人工核验视图</summary><pre>{JSON.stringify({ source_facts: variant.facts, effective_facts: variant.effective_facts, curation: variant.curation }, null, 2)}</pre></details></details>)}</div>
  </>;
}

function EvidenceDetail({ evidence, kind }: { evidence: Evidence; kind: "tire" | "vehicle" }) {
  const url = safeExternalUrl(evidence.source_url);
  return <div className="evidence-detail"><span className="tag quiet">{kind === "vehicle" ? "车型原始快照" : "轮胎原始快照"}</span><h3>{kind === "vehicle" ? "车型来源记录" : "轮胎来源记录"}</h3><dl><div><dt>来源标识</dt><dd>{evidence.source_id}</dd></div><div><dt>原始页面</dt><dd>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{evidence.source_url}<Icon name="external" size={12} /></a> : evidence.source_url}</dd></div><div><dt>观察时间</dt><dd>{formatTime(evidence.observed_at)}</dd></div><div><dt>验证时间</dt><dd>{formatTime(evidence.verified_at)}</dd></div><div><dt>解析器版本</dt><dd className="mono">{evidence.parser_version}</dd></div><div><dt>SHA-256 内容校验值</dt><dd className="hash-value">{evidence.raw_hash}</dd></div><div><dt>快照 ID</dt><dd className="hash-value">{evidence.id}</dd></div></dl>{evidence.quality_review ? <div className="snapshot-banner"><strong>缺失变化经人工确认后在线采纳</strong><span>{evidence.quality_review.operator} · {formatTime(evidence.quality_review.created_at)}</span><p>{evidence.quality_review.reason}</p><span>审批记录 {evidence.quality_review.id}</span></div> : null}<details className="raw-evidence"><summary>查看原始内容<span className="mono">TEXT</span></summary><p>按纯文本展示，保留来源内容。内容类型：{evidence.content_type}</p><pre>{typeof evidence.body === "string" ? evidence.body : JSON.stringify(evidence.body, null, 2)}</pre></details></div>;
}

function SourceReason({ reason }: { reason?: string | null }) {
  const code = reason?.trim() || "";
  const message = reasonLabels[code];
  const displayCode = /^[a-z][a-z0-9_-]{0,79}$/i.test(code) ? code : "unclassified_error";
  return <div className="source-reason"><p>{message || "在线来源暂时无法完成本次查询，请稍后重试。"}</p>{code && !message ? <details><summary>查看错误码</summary><code>{displayCode}</code></details> : null}</div>;
}

function ConflictDetails({ conflicts }: { conflicts: SourceFieldConflict[] }) {
  const labels: Record<string, string> = { extraLoad: "加强型字段 extraLoad", manufMarkings: "技术标记 manufMarkings" };
  return <div className="conflict-items">{conflicts.map((conflict, index) => <div className="conflict-item" key={`${conflict.field}-${conflict.variant_id || ""}-${index}`}><strong>{conflictFieldLabel(conflict.field)}：{conflict.resolution === "resolved" ? "已有裁定记录" : "待核验"}</strong><ul>{conflict.values.map((value, valueIndex) => <li key={valueIndex}><span>{labels[value.source_field || ""] || value.source_field || value.source_id || "来源字段"}</span><b>{typeof value.value === "boolean" ? `${displayValue(value.value)}（${String(value.value)}）` : displayValue(value.value)}</b></li>)}</ul></div>)}</div>;
}
