/**
 * 日报页 —— 对齐平台B契约 §3.7、§9
 *
 * 日报列表、详情、HTML/CSV 导出
 */
import { useEffect, useState } from 'react';
import { Table, Typography, Button, Space, Drawer, Descriptions, Tag, message } from 'antd';
import { DownloadOutlined, EyeOutlined } from '@ant-design/icons';
import { mockReports } from '../../api/mock';
import type { DailyReport } from '../../api/types';
import dayjs from 'dayjs';

export default function Reports() {
  const [reports, setReports] = useState<DailyReport[]>([]);
  const [selected, setSelected] = useState<DailyReport | null>(null);

  useEffect(() => {
    setReports(mockReports);
  }, []);

  const handleExport = (day: string, format: 'html' | 'csv') => {
    // TODO: 真实接口: GET /reports/daily/{day}/export?format=html|csv
    message.info(`导出 ${day} ${format.toUpperCase()}（mock）`);
  };

  const columns = [
    {
      title: '日期', dataIndex: 'day', key: 'day', width: 120,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    { title: '检测总量', dataIndex: 'total', key: 'total', width: 100 },
    {
      title: '合格', dataIndex: 'auto_pass', key: 'auto_pass', width: 80,
      render: (v: number, r: DailyReport) => `${v} (${((v / r.total) * 100).toFixed(1)}%)`,
    },
    { title: '待复审', dataIndex: 'recheck', key: 'recheck', width: 80 },
    { title: '人工介入', dataIndex: 'manual', key: 'manual', width: 80 },
    { title: '坏图', dataIndex: 'bad_count', key: 'bad_count', width: 60 },
    {
      title: '操作', key: 'action', width: 180,
      render: (_: unknown, record: DailyReport) => (
        <Space>
          <a onClick={() => setSelected(record)}><EyeOutlined /> 详情</a>
          <a onClick={() => handleExport(record.day, 'html')}><DownloadOutlined /> HTML</a>
          <a onClick={() => handleExport(record.day, 'csv')}><DownloadOutlined /> CSV</a>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="page-header">
        <Typography.Title level={4}>日报</Typography.Title>
        <Typography.Text type="secondary">
          每日 00:10 自动生成，保留 90 天。支持 HTML / CSV 导出。
        </Typography.Text>
      </div>

      <Table
        columns={columns}
        dataSource={reports}
        rowKey="day"
        size="small"
        pagination={false}
      />

      {/* 日报详情抽屉 */}
      <Drawer
        title={`日报详情 ${selected?.day}`}
        open={!!selected}
        onClose={() => setSelected(null)}
        width={500}
      >
        {selected && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="日期">{selected.day}</Descriptions.Item>
            <Descriptions.Item label="检测总量">{selected.total}</Descriptions.Item>
            <Descriptions.Item label="合格">
              {selected.auto_pass} ({((selected.auto_pass / selected.total) * 100).toFixed(1)}%)
            </Descriptions.Item>
            <Descriptions.Item label="待复审">
              {selected.recheck} ({((selected.recheck / selected.total) * 100).toFixed(1)}%)
            </Descriptions.Item>
            <Descriptions.Item label="人工介入">
              {selected.manual} ({((selected.manual / selected.total) * 100).toFixed(1)}%)
            </Descriptions.Item>
            <Descriptions.Item label="坏图">{selected.bad_count}</Descriptions.Item>
            <Descriptions.Item label="合格率">
              <Tag color="green">{((selected.auto_pass / selected.total) * 100).toFixed(1)}%</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="错图率">
              <Tag color="orange">{(((selected.recheck + selected.manual + selected.bad_count) / selected.total) * 100).toFixed(1)}%</Tag>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}