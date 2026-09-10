/**
 * 工位与相机页 —— 对齐平台B契约 §3.3、§5
 *
 * 8路监控墙 + 每工位模板编辑（无"模板预设"概念）。
 * 产线工人操作：看画面 → 点"模板"按钮 → 编辑该工位模板（选模型→勾类别→调阈值）→ 保存
 * 管理员操作：点齿轮 → 模板管理 → 编辑参数 → 保存
 */
import { useEffect, useState } from 'react';
import {
  Tag, Button, Typography, Space, Modal, Form, Input, Select,
  Switch, Drawer, InputNumber, message, Card,
} from 'antd';
import {
  PlusOutlined, EditOutlined, CameraOutlined, ThunderboltOutlined,
  WifiOutlined, SwapOutlined,
} from '@ant-design/icons';
import { mockStations, mockModels } from '../../api/mock';
import type { StationInfo, StationTemplate, TemplateObject } from '../../api/types';

const statusColors: Record<string, string> = {
  online: '#52c41a', offline: '#8c8c8c', error: '#ff4d4f',
};

const verdictLabels: Record<string, string> = {
  auto_pass: '合格', recheck: '复审', manual: '人工', unknown: '待机',
};

const mockLastVerdict: Record<string, string> = {
  ST01: 'auto_pass', ST02: 'recheck', ST03: 'auto_pass', ST04: 'auto_pass',
  ST05: 'manual', ST06: 'auto_pass', ST07: 'unknown', ST08: 'unknown',
};

export default function Stations() {
  const [stations, setStations] = useState<StationInfo[]>([]);
  const [editStation, setEditStation] = useState<StationInfo | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [templateDrawer, setTemplateDrawer] = useState<{ station: StationInfo } | null>(null);
  const [form] = Form.useForm();

  useEffect(() => { setStations(mockStations); }, []);

  // 帧计数（mock视觉心跳）
  const [frameCounts, setFrameCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    const timer = setInterval(() => {
      setFrameCounts(prev => {
        const next: Record<string, number> = {};
        stations.filter(s => s.status === 'online' && s.enabled).forEach(s => {
          next[s.code] = ((prev[s.code] || 0) + 1) % 9999;
        });
        return next;
      });
    }, 500);
    return () => clearInterval(timer);
  }, [stations]);

  const handleSaveStation = () => {
    form.validateFields().then((values) => {
      if (editStation) {
        setStations(prev => prev.map(s => s.code === editStation.code ? { ...s, ...values } : s));
        message.success('工位已更新');
      } else {
        setStations(prev => [...prev, { ...values, status: 'offline', template_version: 0, enabled: false }]);
        message.success('工位已创建');
      }
      setEditModalOpen(false); setEditStation(null); form.resetFields();
    });
  };

  const handleDelete = (code: string) => {
    setStations(prev => prev.filter(s => s.code !== code));
    message.success('工位已删除');
  };
  const handleToggle = (code: string, enabled: boolean) => {
    setStations(prev => prev.map(s => s.code === code ? { ...s, enabled } : s));
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>工位监控</Typography.Title>
        <Space>
          <Tag color="green" icon={<WifiOutlined />}>{stations.filter(s => s.status === 'online').length}/{stations.length} 在线</Tag>
          <Button icon={<PlusOutlined />} onClick={() => { setEditStation(null); form.resetFields(); setEditModalOpen(true); }}>新增工位</Button>
        </Space>
      </div>

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gridTemplateRows: 'repeat(2, 1fr)', gap: 10, minHeight: 0 }}>
        {stations.map(station => (
          <CameraSlot
            key={station.code}
            station={station}
            frameCount={frameCounts[station.code] || 0}
            lastVerdict={mockLastVerdict[station.code] || 'unknown'}
            onToggle={(enabled) => handleToggle(station.code, enabled)}
            onEdit={() => { setEditStation(station); form.setFieldsValue(station); setEditModalOpen(true); }}
            onTemplate={() => setTemplateDrawer({ station })}
          />
        ))}
      </div>

      <Modal title={editStation ? '编辑工位' : '新增工位'} open={editModalOpen} onOk={handleSaveStation} onCancel={() => { setEditModalOpen(false); setEditStation(null); }}>
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="工位编码" rules={[{ required: true }]}>
            <Input placeholder="如 ST01" disabled={!!editStation} />
          </Form.Item>
          <Form.Item name="name" label="工位名称" rules={[{ required: true }]}>
            <Input placeholder="如 1号线-左门板" />
          </Form.Item>
          <Form.Item name="channel_id" label="通道ID">
            <Input placeholder="如 ch01" />
          </Form.Item>
        </Form>
      </Modal>

      <TemplateDrawer open={templateDrawer} onClose={() => setTemplateDrawer(null)} models={mockModels} stationTemplates={{}} />
    </div>
  );
}

/** 单个相机槽位 */
function CameraSlot({
  station, frameCount, lastVerdict,
  onToggle, onEdit, onTemplate,
}: {
  station: StationInfo; frameCount: number; lastVerdict: string;
  onToggle: (enabled: boolean) => void;
  onEdit: () => void; onTemplate: () => void;
}) {
  const isOnline = station.status === 'online' && station.enabled;

  return (
    <div style={{ position: 'relative', border: `2px solid ${isOnline ? statusColors.online : '#333'}`, borderRadius: 8, overflow: 'hidden', background: '#1a1a2e', display: 'flex', flexDirection: 'column' }}>
      {/* 画面 */}
      <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', background: isOnline ? 'radial-gradient(ellipse at center, #1a3a1a 0%, #0a0a15 100%)' : '#0d0d1a', minHeight: 0 }}>
        {isOnline ? (
          <>
            <div style={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(rgba(0,255,0,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(0,255,0,0.06) 1px, transparent 1px)', backgroundSize: '40px 40px' }} />
            <div style={{ position: 'absolute', top: '50%', left: '50%', width: 60, height: 60, transform: 'translate(-50%, -50%)', border: '1px solid rgba(0,255,0,0.12)', borderRadius: '50%' }} />
            <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: 1, background: 'rgba(0,255,0,0.08)' }} />
            <div style={{ position: 'absolute', top: 0, bottom: 0, left: '50%', width: 1, background: 'rgba(0,255,0,0.08)' }} />
            <span style={{ position: 'absolute', bottom: 4, right: 6, color: 'rgba(0,255,0,0.4)', fontFamily: 'monospace', fontSize: 10 }}>#{String(frameCount).padStart(4, '0')}</span>
            <span style={{ position: 'absolute', top: 6, right: 8, width: 8, height: 8, borderRadius: '50%', background: '#52c41a', animation: 'blink 1s ease-in-out infinite' }} />
          </>
        ) : (
          <div style={{ textAlign: 'center', opacity: 0.3 }}>
            <CameraOutlined style={{ fontSize: 36, color: '#555' }} />
            <div style={{ color: '#555', fontSize: 11, marginTop: 6 }}>{station.status === 'error' ? '相机断连' : '未启用'}</div>
          </div>
        )}
      </div>

      {/* 底部栏 */}
      <div style={{ background: '#0d0d1a', padding: '6px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid #1a1a2e' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, flex: 1 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: isOnline ? '#52c41a' : '#555' }} />
          <span style={{ color: '#ccc', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{station.name}</span>
          <Tag color={lastVerdict === 'recheck' ? 'gold' : lastVerdict === 'manual' ? 'red' : lastVerdict === 'auto_pass' ? 'green' : 'default'} style={{ fontSize: 10, lineHeight: '16px', margin: 0, flexShrink: 0 }}>{verdictLabels[lastVerdict]}</Tag>
        </div>
        <Space size={2}>
          <Button size="small" type="text" icon={<SwapOutlined />} onClick={onTemplate}
            style={{ color: '#aaa', fontSize: 11, padding: '0 4px' }}>
            {station.template_version > 0 ? `模板 v${station.template_version}` : '配置模板'}
          </Button>
          <Switch size="small" checked={station.enabled} onChange={onToggle} />
          <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} style={{ color: '#666', fontSize: 11, padding: '0 2px' }} />
        </Space>
      </div>
    </div>
  );
}

/** 管理员模板编辑抽屉 */
function TemplateDrawer({
  open, onClose, models, stationTemplates,
}: {
  open: { station: StationInfo } | null; onClose: () => void;
  models: { model_ref: string; classes: string[] }[];
  stationTemplates: Record<string, StationTemplate>;
}) {
  const [template, setTemplate] = useState<StationTemplate | null>(null);

  useEffect(() => {
    if (open) {
      const tpl = stationTemplates[open.station.code];
      if (tpl) {
        setTemplate({
          template_version: open.station.template_version || 1,
          model_ref: tpl.model_ref,
          skillname: tpl.skillname,
          tile_size: tpl.tile_size,
          overlap: tpl.overlap,
          objects: tpl.objects.map(o => ({ ...o, thresholds: { ...o.thresholds } })),
        });
      } else {
        // 未配置模板：从第一个模型 + 空对象起步
        setTemplate({
          template_version: 0,
          model_ref: models[0]?.model_ref || '',
          skillname: 'ObjectDetection',
          tile_size: 1280,
          overlap: 0.2,
          objects: [],
        });
      }
    }
  }, [open]);

  if (!open || !template) return null;

  return (
    <Drawer title={`模板管理 - ${open.station.code}`} open={!!open} onClose={onClose} width={520}
      extra={<Button type="primary" onClick={() => { message.success('模板已保存（mock）'); onClose(); }}>保存模板</Button>}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <Typography.Text strong>模型选择</Typography.Text>
          <Select style={{ width: '100%', marginTop: 4 }} value={template.model_ref}
            onChange={(v) => setTemplate({ ...template, model_ref: v })}
            options={models.map(m => ({ value: m.model_ref, label: `${m.model_ref} (${m.classes.length}类)` }))} />
        </div>
        <div>
          <Typography.Text strong>切片参数</Typography.Text>
          <Space style={{ marginTop: 4 }}>
            <span>切片大小:</span><InputNumber min={320} max={2560} step={64} value={template.tile_size} onChange={(v) => setTemplate({ ...template, tile_size: v || 1280 })} />
            <span>重叠率:</span><InputNumber min={0} max={0.5} step={0.05} value={template.overlap} onChange={(v) => setTemplate({ ...template, overlap: v || 0.2 })} />
          </Space>
        </div>
        <div>
          <Typography.Text strong>检测对象与阈值</Typography.Text>
          {template.objects.map((obj: TemplateObject, i: number) => (
            <Card key={obj.code} size="small" style={{ marginTop: 8 }}>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Tag color="blue">{obj.code}</Tag>
                <Space>
                  <span>复审阈值:</span><InputNumber min={0} max={1} step={0.05} value={obj.thresholds.recheck_min}
                    onChange={(v) => { const o = [...template.objects]; o[i].thresholds.recheck_min = v || 0.5; setTemplate({ ...template, objects: o }); }} />
                  <span>自动放行:</span><InputNumber min={0} max={1} step={0.05} value={obj.thresholds.auto_min}
                    onChange={(v) => { const o = [...template.objects]; o[i].thresholds.auto_min = v || 0.9; setTemplate({ ...template, objects: o }); }} />
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>规则: 0 &lt; 复审阈值 &lt; 自动放行 &lt; 1</Typography.Text>
              </Space>
            </Card>
          ))}
        </div>
      </Space>
    </Drawer>
  );
}