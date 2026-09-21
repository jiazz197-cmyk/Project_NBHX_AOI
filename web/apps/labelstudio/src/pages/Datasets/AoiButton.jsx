/**
 * 数据集页统一按钮（D5 收尾第六轮）。
 *
 * 为什么不用 `@humansignal/ui` 的 Button：compact + outlined 在这套页面里偏"半透明灰"，
 * 与台面/账本的工程感不搭。这里只做一层薄封装，样式全部落在 `Datasets.css` 的
 * `.aoi-ds__btn*`（跟随主题语义 token），需要宿主能力时仍可直接用 Button。
 *
 * kind：primary（墨色实底）| ghost（发丝描边，缺省）| quiet（无边框文字）| danger | onStage（深底台上的反白）
 */
const KIND_CLASS = {
  primary: "aoi-ds__btn--primary",
  ghost: "aoi-ds__btn--ghost",
  quiet: "aoi-ds__btn--quiet",
  danger: "aoi-ds__btn--danger",
  onStage: "aoi-ds__btn--on-stage",
};

export const AoiButton = ({ kind = "ghost", className = "", type = "button", children, ...rest }) => (
  <button type={type} className={`aoi-ds__btn ${KIND_CLASS[kind] ?? KIND_CLASS.ghost} ${className}`} {...rest}>
    {children}
  </button>
);
