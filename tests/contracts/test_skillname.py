"""T1.2 skillname 契约测试（零三方依赖）。"""

import dataclasses

import pytest
import skillname
from skillname import (
    FAULT_CODE_PALETTE,
    DatasetSubset,
    ModelLifecycle,
    ModelRef,
    SkillName,
    Verdict,
    color_for_index,
    fault_code_index,
    format_fault_code,
    image_tag_from_model_ref,
    is_valid_fault_code,
    ls_control_for,
    parse_model_ref,
)


class TestSkillName:
    def test_object_detection_is_mvp_skill(self):
        assert SkillName.OBJECT_DETECTION.value == 'ObjectDetection'
        assert str(SkillName.OBJECT_DETECTION) == 'ObjectDetection'
        assert SkillName('ObjectDetection') is SkillName.OBJECT_DETECTION

    def test_reserved_skills_are_declared(self):
        assert {s.value for s in SkillName} == {
            'ObjectDetection',
            'ImageClassification',
            'ImageSegmentation',
        }

    def test_skill_to_ls_control(self):
        assert ls_control_for(SkillName.OBJECT_DETECTION) == 'RectangleLabels'
        assert ls_control_for('ObjectDetection') == 'RectangleLabels'

    def test_reserved_skill_has_no_ls_control(self):
        with pytest.raises(ValueError):
            ls_control_for(SkillName.IMAGE_CLASSIFICATION)

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError):
            ls_control_for('Classification')

    @pytest.mark.parametrize(
        ('enum_cls', 'values'),
        [
            (ModelLifecycle, {'candidate', 'approved', 'published', 'retired'}),
            (DatasetSubset, {'train', 'val', 'test'}),
            (Verdict, {'auto_pass', 'recheck', 'manual'}),
        ],
    )
    def test_other_enums(self, enum_cls, values):
        assert {e.value for e in enum_cls} == values


class TestFaultCodes:
    @pytest.mark.parametrize(
        'code',
        [
            # 历史字面量写法（超集：仍然合法，存量数据零迁移）
            'object_fault_type_01',
            'object_fault_type_99',
            # D5 收尾第二轮：前缀改为两段可变英文词 <object>_<fault_type>
            'panel_scratch_01',
            'glass_dent_02',
            'inner_surface_oil_stain_07',
            'outer_panel_surface_scratch_99',
        ],
    )
    def test_valid_codes(self, code):
        assert is_valid_fault_code(code) is True

    @pytest.mark.parametrize(
        'code',
        [
            None,
            1,
            'object_fault_type_1',
            'object_fault_type_100',
            'object_fault_type_ab',
            'object_fault_type_01 ',
            'object_fault_type_01\n',
            'Object_fault_type_01',
            # P0：00 非法（01~99），且 \d 的 Unicode 语义必须被禁止
            'object_fault_type_00',
            'object_fault_type_０１',
            'object_fault_type_٠١',
            'object_fault_type_⁰¹',
            # 放宽后仍需拒绝：大写/连字符/中划线/无编号/编号越界/00/超长前缀
            'Panel_scratch_01',
            'panel-scratch_01',
            'panel scratch_01',
            'panel_scratch',
            'panel_scratch_1',
            'panel_scratch_100',
            'panel_scratch_00',
            '_panel_scratch_01',
            'panel_scratch_0１',
            f'{"p" * 29}_scratch_01',  # 前缀 29 > 28（VARCHAR(32) 预算）
        ],
    )
    def test_invalid_codes(self, code):
        assert is_valid_fault_code(code) is False

    def test_format_and_index_roundtrip(self):
        for index in (1, 2, 9, 10, 99):
            code = format_fault_code(index)
            assert code == f'object_fault_type_{index:02d}'  # 缺省前缀向后兼容
            assert is_valid_fault_code(code)
            assert fault_code_index(code) == index

    def test_format_with_variable_prefix(self):
        """D5 收尾第二轮：前缀可传 <object>_<fault_type>，编号后缀保持 01~99。"""
        code = format_fault_code(3, prefix='panel_scratch')
        assert code == 'panel_scratch_03'
        assert is_valid_fault_code(code)
        # fault_code_index 返回 code 自身编号，与类别索引无关
        assert fault_code_index(code) == 3

    @pytest.mark.parametrize('prefix', ['', 'Panel_scratch', 'panel-scratch', 'panel_', 'p' * 29, None, 3])
    def test_format_invalid_prefix(self, prefix):
        with pytest.raises((ValueError, TypeError)):
            format_fault_code(1, prefix=prefix)

    @pytest.mark.parametrize('index', [0, 100, -1, 1.5, True])
    def test_format_out_of_range(self, index):
        with pytest.raises((ValueError, TypeError)):
            format_fault_code(index)

    def test_fault_code_index_invalid(self):
        with pytest.raises(ValueError):
            fault_code_index('object_fault_type_1')

    def test_palette_is_fixed_and_cycles(self):
        assert len(FAULT_CODE_PALETTE) == 8
        assert len(set(FAULT_CODE_PALETTE)) == 8
        for index in range(16):
            assert color_for_index(index) == FAULT_CODE_PALETTE[index % 8]

    def test_palette_invalid_index(self):
        with pytest.raises(ValueError):
            color_for_index(-1)


class TestModelRef:
    def test_parse_valid(self):
        ref = parse_model_ref('3-yolo@ds1')
        assert ref == ModelRef(seq=3, framework='yolo', dataset_version='1')
        assert str(ref) == '3-yolo@ds1'

    @pytest.mark.parametrize(
        'value',
        [
            '3-yolo@ds',
            '3-yolo-ds1',
            '3-YOLO@ds1',
            '-yolo@ds1',
            '3-yolo@dsx',
            '3-yolo@ds1-extra',
            '3 yolo@ds1',
            '',
            # P0：\d 的 Unicode 语义必须被禁止（镜像 tag 只能 ASCII）
            '3-yolo@ds١',
            '٣-yolo@ds1',
            '3-yolo@ds１',
        ],
    )
    def test_parse_invalid(self, value):
        with pytest.raises(ValueError):
            parse_model_ref(value)

    def test_parse_accepts_model_ref_instance(self):
        ref = ModelRef(1, 'yolo', '2')
        assert parse_model_ref(ref) is ref

    def test_frozen_dataclass(self):
        ref = ModelRef(1, 'yolo', '1')
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.seq = 2  # type: ignore[misc]

    @pytest.mark.parametrize(
        ('model_ref', 'precision', 'expected'),
        [
            ('3-yolo@ds1', None, '3-yolo-ds1'),
            ('3-yolo@ds1', 'fp32', '3-yolo-ds1'),
            ('3-yolo@ds1', 'fp16', '3-yolo-ds1-fp16'),
            ('3-yolo@ds1', 'int8', '3-yolo-ds1-int8'),
            (ModelRef(12, 'yolo11', '7'), 'fp16', '12-yolo11-ds7-fp16'),
        ],
    )
    def test_image_tag(self, model_ref, precision, expected):
        assert image_tag_from_model_ref(model_ref, precision) == expected

    def test_image_tag_invalid_precision(self):
        with pytest.raises(ValueError):
            image_tag_from_model_ref('3-yolo@ds1', 'fp64')

    def test_image_tag_rejects_non_ascii_model_ref(self):
        """P0：非 ASCII 数字的 model_ref 不能生成镜像 tag（registry 只接受 ASCII）。"""
        with pytest.raises(ValueError):
            image_tag_from_model_ref('3-yolo@ds١', 'fp16')

    def test_reexports(self):
        for name in skillname.__all__:
            assert hasattr(skillname, name), name
