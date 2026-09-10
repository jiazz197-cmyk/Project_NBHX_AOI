/**
 * 概览页 —— 对齐平台B契约 §9 前端页面定义
 *
 * 展示：今日检测量、三档分布、合格率/错图率、缺陷TopN、节拍、时延P95、工位在线、outbox状态
 */
import { useEffect, useState } from 'react';
import { Row, Col, Card, Statistic, Table, Tag, Typography, Space } from 'antd';
import {
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { mockStatsSummary, mockTrend } from '../../api/mock';
import type { StatsSummary, TrendPoint } from '../../api/types';

const verdictColors: Record<string, string> = {
  auto_pass: '#52c41a',
  recheck: '#faad14',
  manual: '#ff4d4f',
};

const verdictLabels: Record<string, string> = {
  auto_pass: '合格',
  recheck: '待复审',
  manual: '人工介入',
};

export default function Dashboard() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);

  useEffect(() => {
    // TODO: 后续替换为真实API调用
    // const data = await get<StatsSummary>('/stats/summary', { range: 'today' });
    setStats(mockStatsSummary);
    setTrend(mockTrend);
  }, []);

  if (!stats) return null;

  // 三档分布饼图
  const verdictPieOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      data: [
        { value: stats.auto_pass, name: '合格', itemStyle: { color: '#52c41a' } },
        { value: stats.recheck, name: '待复审', itemStyle: { color: '#faad14' } },
        { value: stats.manual, name: '人工介入', itemStyle: { color: '#ff4d4f' } },
      ],
      label: { show: false },
      emphasis: { label: { show: true } },
    }],
  };

  // 今日检测趋势（柱状+折线）
  const trendOption = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['检测量', '合格', '待复审', '人工介入'], bottom: 0 },
    grid: { left: 40, right: 40, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: trend.map(t => t.time) },
    yAxis: { type: 'value' },
    series: [
      { name: '检测量', type: 'bar', data: trend.map(t => t.total), itemStyle: { color: '#1677ff' }, barWidth: 6 },
      { name: '合格', type: 'bar', data: trend.map(t => t.auto_pass), itemStyle: { color: '#52c41a' }, barWidth: 6 },
      { name: '待复审', type: 'bar', data: trend.map(t => t.recheck), itemStyle: { color: '#faad14' }, barWidth: 6 },
      { name: '人工介入', type: 'bar', data: trend.map(t => t.manual), itemStyle: { color: '#ff4d4f' }, barWidth: 6 },
    ],
  };

  // 缺陷TopN表格
  const defectColumns = [
    { title: '缺陷类型', dataIndex: 'name_cn', key: 'name_cn' },
    { title: '缺陷编码', dataIndex: 'code', key: 'code', render: (c: string) => <Tag>{c}</Tag> },
    { title: '框数', dataIndex: 'count', key: 'count' },
    { title: '涉及图片数', dataIndex: 'image_count', key: 'image_count' },
  ];

  return (
    <div>
      <div className="page-header">
        <Typography.Title level={4}>概览</Typography.Title>
      </div>

      {/* 第一行：核心指标卡片 */}
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="今日检测量" value={stats.total} prefix={<RobotOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="合格率" value={stats.pass_rate} suffix="%" precision={1} valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="平均时延" value={stats.avg_latency_ms} suffix="ms" prefix={<ClockCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="工位在线" value={`${stats.stations_online}/${stats.stations_total}`} prefix={<WarningOutlined />} />
          </Card>
        </Col>
      </Row>

      {/* 第二行：三档分布 + 缺陷TopN */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={12}>
          <Card title="三档判定分布" size="small">
            <Row gutter={16}>
              <Col span={12}>
                <ReactECharts option={verdictPieOption} style={{ height: 220 }} />
              </Col>
              <Col span={12}>
                <Space direction="vertical" style={{ width: '100%', paddingTop: 30 }}>
                  {['auto_pass', 'recheck', 'manual'].map(v => (
                    <div key={v} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Tag color={verdictColors[v]}>{verdictLabels[v]}</Tag>
                      <span>{stats[v as keyof StatsSummary] as number}</span>
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
                    <Tag color="red">坏图</Tag>
                    <span>{stats.bad_count}</span>
                  </div>
                </Space>
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="缺陷 TopN" size="small">
            <Table
              columns={defectColumns}
              dataSource={stats.defect_topn}
              rowKey="code"
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
      </Row>

      {/* 第三行：今日趋势 */}
      <Row style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="今日检测趋势" size="small">
            <ReactECharts option={trendOption} style={{ height: 300 }} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}