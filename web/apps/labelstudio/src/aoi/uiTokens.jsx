/**
 * AOI 数据集页共享样式常量（Tailwind 语义 token 映射）。
 * 全部取自 @humansignal/ui 设计 token（libs/ui tokens.js → tailwind colors），
 * 随 html[data-color-scheme="dark"] 自动翻转，禁止写死十六进制色值。
 */

/** 页面壳：与 LS 原生页同高、同底色 */
export const PAGE = "min-h-[calc(100vh-var(--header-height))] bg-neutral-background text-neutral-content";

/** 卡片容器：LS 新 UI 卡片风（浅边框 + 大圆角 + surface 底） */
export const CARD = "rounded-xl border border-neutral-border-subtle bg-neutral-surface";

/** 输入控件：跟随主题的 input/select */
export const INPUT =
  "rounded-md border border-neutral-border bg-neutral-surface px-3 py-1.5 text-sm text-neutral-content " +
  "placeholder:text-neutral-content-subtlest outline-none focus:border-primary-border-bold " +
  "focus:outline focus:outline-2 focus:outline-primary-focus-outline disabled:opacity-50";

/** 表格骨架：容器卡 + 表头/行分隔，全部走 token */
export const TABLE = "w-full border-collapse text-sm";
export const TABLE_HEAD_CELL =
  "px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-content-subtle";
export const TABLE_BODY_CELL = "px-4 py-2.5 align-middle text-neutral-content";
export const TABLE_ROW = "border-t border-neutral-border-subtle transition-colors hover:bg-neutral-surface-hover";

/** 徽章：kind ∈ positive | negative | primary | neutral */
const BADGE_KIND = {
  positive: "bg-positive-surface text-positive-content border-positive-border",
  negative: "bg-negative-surface text-negative-content border-negative-border",
  primary: "bg-primary-surface text-primary-content border-primary-border",
  neutral: "bg-neutral-surface-inset text-neutral-content-subtle border-neutral-border-subtle",
};

/** 状态徽章（字典启停 / 质检 / 风险档通用） */
export const badge = (kind, label) => (
  <span
    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${BADGE_KIND[kind] ?? BADGE_KIND.neutral}`}
  >
    {label}
  </span>
);

/** 空态与加载态 */
export const EMPTY = "px-4 py-10 text-center text-sm text-neutral-content-subtler";
export const LOADING = "flex items-center justify-center px-4 py-10 text-sm text-neutral-content-subtle gap-2";
export const ERROR_BOX =
  "rounded-lg border border-negative-border bg-negative-surface px-4 py-3 text-sm text-negative-content";

/** 区块小节标题（卡片内） */
export const SECTION_TITLE = "text-sm font-semibold text-neutral-content";
export const HINT = "text-xs leading-5 text-neutral-content-subtle";
