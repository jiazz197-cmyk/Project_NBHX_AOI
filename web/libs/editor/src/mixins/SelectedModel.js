import { types } from "mobx-state-tree";

import Tree from "../core/Tree";
import { isDefined } from "../utils/utilities";

const SelectedModelMixin = types
  .model()
  .volatile(() => {
    return {
      isSeparated: false,
    };
  })
  .views((self) => ({
    get tiedChildren() {
      return Tree.filterChildrenOfType(self, self._child);
    },

    get selectedLabels() {
      return self.tiedChildren.filter((c) => c.selected === true);
    },

    getSelectedColor() {
      // return first selected label color
      const sel = self.tiedChildren.find((c) => c.selected === true);

      return sel && sel.background;
    },

    get selectedColor() {
      // return first selected label color
      const sel = self.tiedChildren.find((c) => c.selected === true);

      return sel && sel.background;
    },

    get isSelected() {
      return self.selectedLabels.length > 0;
    },

    // right now this is duplicate code from the above and it's done for clarity
    get holdsState() {
      return self.selectedLabels.length > 0;
    },

    selectedValues() {
      return self.selectedLabels.map((c) => (c.alias ? c.alias : c.value)).filter((val) => isDefined(val));
    },

    getResultValue() {
      return {
        [self.valueType]: self.selectedValues(),
      };
    },

    // return labels that are selected and have an alias only
    get selectedAliases() {
      return self.selectedLabels.filter((c) => c.alias).map((c) => c.alias);
    },

    // AOI 二开（注入点 #5，D5 收尾 #2）：展示名优先 html（缺陷字典中文名），
    // 结果值仍走 selectedValues()（= code），两者必须分离——alias 会污染结果值。
    getSelectedDisplayString(joinstr = " ") {
      return self.selectedLabels
        .map((c) => c.html || c.value)
        .filter((val) => isDefined(val))
        .join(joinstr);
    },

    getSelectedString(joinstr = " ") {
      return self.selectedValues().join(joinstr);
    },

    findLabel(value) {
      return self.tiedChildren.find(
        (c) =>
          (c.alias === value && isDefined(value)) || c.value === value || (!isDefined(c.value) && !isDefined(value)),
      );
    },

    get emptyLabel() {
      return self.allowempty ? self.findLabel(null) : null;
    },
  }))
  .actions((self) => ({
    /**
     * Get current color from Label settings
     */
    unselectAll() {
      self.tiedChildren.forEach((c) => c.setSelected(false));
    },

    checkMaxUsages() {
      return self.tiedChildren.filter((c) => !c.canBeUsed());
    },

    selectFirstVisible() {
      const f = self.tiedChildren.find((c) => c.visible);

      f && f.toggleSelected();

      return f;
    },

    /**
     * Change states of tags according to values from result
     * @param {string|string[]} value
     */
    updateFromResult(value) {
      self.unselectAll();
      const values = Array.isArray(value) ? (value.length ? value : [null]) : [value];

      if (values.length) {
        values.map((v) => self.findLabel(v)).forEach((label) => label?.setSelected(true));
      } else if (self.allowempty) {
        self.findLabel(null)?.setSelected(true);
      }
    },
  }));

export default SelectedModelMixin;
