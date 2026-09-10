/**
 * 检测记录页 —— 对齐平台B契约 §3.5、§9
 *
 * 列表 + 筛选（工位/判定/时间/回传状态）+ 图片与框预览
 */
import { useEffect, useState } from 'react';
import { Table, Tag, Select, DatePicker, Space, Typography, Drawer, Descriptions } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { mockInspections } from '../../api/mock';
import type { InspectionRecord } from '../../api/types';
import dayjs from 'dayjs';

const { RangePicker } = DatePicker;

const verdictColors: Record<string, string> = {
  auto_pass: 'green',
  recheck: 'gold',
  manual: 'red',
};

const verdictLabels: Record<string, string> = {
  auto_pass: '合格',
  recheck: '待复审',
  manual: '人工介入',
};

const pushedStatusColors: Record<string, string> = {
  'n/a': 'default',
  pending: 'blue',
  pushing: 'processing',
  pushed: 'green',
  dead: 'red',
};

const pushedStatusLabels: Record<string, string> = {
  'n/a': '无需回传',
  pending: '待回传',
  pushing: '回传中',
  pushed: '已回传',
  dead: '已死信',
};

export default function Inspections() {
  const [records, setRecords] = useState<InspectionRecord[]>([]);
  const [selected, setSelected] = useState<InspectionRecord | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<string | undefined>();
  const [stationFilter, setStationFilter] = useState<string | undefined>();

  useEffect(() => {
    setRecords(mockInspections);
  }, []);

  const filtered = records.filter(r => {
    if (verdictFilter && r.verdict !== verdictFilter) return false;
    if (stationFilter && r.station_code !== stationFilter) return false;
    return true;
  });

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    { title: '工位', dataIndex: 'station_code', key: 'station_code', width: 80 },
    { title: '序号', dataIndex: 'seq', key: 'seq', width: 70 },
    {
      title: '判定', dataIndex: 'verdict', key: 'verdict', width: 100,
      render: (v: string) => <Tag color={verdictColors[v]}>{verdictLabels[v]}</Tag>,
    },
    {
      title: '判定原因', dataIndex: 'verdict_reasons', key: 'verdict_reasons',
      render: (reasons: string[]) => reasons.map((r: string) => <Tag key={r}>{r}</Tag>),
    },
    { title: '缺陷框数', dataIndex: 'boxes', key: 'boxes', width: 80, render: (boxes: unknown[]) => boxes.length },
    { title: '时延(ms)', dataIndex: 'latency_ms', key: 'latency_ms', width: 90 },
    {
      title: '回传', dataIndex: 'pushed_status', key: 'pushed_status', width: 90,
      render: (v: string) => <Tag color={pushedStatusColors[v]}>{pushedStatusLabels[v]}</Tag>,
    },
    {
      title: '采集时间', dataIndex: 'captured_at', key: 'captured_at', width: 170,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作', key: 'action', width: 60,
      render: (_: unknown, record: InspectionRecord) => (
        <a onClick={() => setSelected(record)}>详情</a>
      ),
    },
  ];

  return (
    <div>
      <div className="page-header">
        <Typography.Title level={4}>检测记录</Typography.Title>
      </div>

      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="工位筛选"
          allowClear
          style={{ width: 140 }}
          value={stationFilter}
          onChange={setStationFilter}
          options={['ST01', 'ST02', 'ST03', 'ST04', 'ST05', 'ST06', 'ST07', 'ST08'].map(s => ({ value: s, label: s }))}
        />
        <Select
          placeholder="判定筛选"
          allowClear
          style={{ width: 130 }}
          value={verdictFilter}
          onChange={setVerdictFilter}
          options={[
            { value: 'auto_pass', label: '合格' },
            { value: 'recheck', label: '待复审' },
            { value: 'manual', label: '人工介入' },
          ]}
        />
        <RangePicker
          placeholder={['开始时间', '结束时间']}
        />
      </Space>

      <Table
        columns={columns}
        dataSource={filtered}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total: number) => `共 ${total} 条` }}
      />

      {/* 详情抽屉 */}
      <Drawer
        title={`检测详情 #${selected?.id}`}
        open={!!selected}
        onClose={() => setSelected(null)}
        width={500}
      >
        {selected && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="ID">{selected.id}</Descriptions.Item>
            <Descriptions.Item label="工位">{selected.station_code}</Descriptions.Item>
            <Descriptions.Item label="序号">{selected.seq}</Descriptions.Item>
            <Descriptions.Item label="判定">
              <Tag color={verdictColors[selected.verdict]}>{verdictLabels[selected.verdict]}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="判定原因">
              {selected.verdict_reasons.map(r => <Tag key={r}>{r}</Tag>)}
            </Descriptions.Item>
            <Descriptions.Item label="时延">{selected.latency_ms}ms</Descriptions.Item>
            <Descriptions.Item label="模板版本">{selected.template_version}</Descriptions.Item>
            <Descriptions.Item label="回传状态">
              <Tag color={pushedStatusColors[selected.pushed_status]}>{pushedStatusLabels[selected.pushed_status]}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="采集时间">{dayjs(selected.captured_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
            <Descriptions.Item label="缺陷框">
              {selected.boxes.length > 0 ? (
                selected.boxes.map((b: { object_code: string; score: number; model_ref: string; xyxy: number[] }, i: number) => (
                  <div key={i} style={{ marginBottom: 4 }}>
                    <Tag>{b.object_code}</Tag>
                    置信度: {b.score.toFixed(2)} |
                    模型: {b.model_ref} |
                    坐标: [{b.xyxy.join(', ')}]
                  </div>
                ))
              ) : '无'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}