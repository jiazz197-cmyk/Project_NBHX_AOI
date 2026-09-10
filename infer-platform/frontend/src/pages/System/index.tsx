/**
 * 系统页 —— 对齐平台B契约 §3.1、§3.2、§9
 *
 * 健康检查、模型库（拉取/离线导入/删除/预加载）、outbox 队列与重推、版本信息
 */
import { useEffect, useState } from 'react';
import {
  Table, Tag, Button, Typography, Space, Card, Row, Col,
  Descriptions, Modal, Input, message, Progress, Statistic,
} from 'antd';
import {
  CloudDownloadOutlined, UploadOutlined, DeleteOutlined,
  ReloadOutlined, ThunderboltOutlined, CheckCircleOutlined,
  CloseCircleOutlined, WarningOutlined, SyncOutlined, ExportOutlined,
} from '@ant-design/icons';
import { mockHealth, mockModels, mockOutbox } from '../../api/mock';
import { get, post } from '../../api/client';
import type { HealthData, ModelInfo, OutboxItem, RemoteModelItem } from '../../api/types';

export default function System() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [outbox, setOutbox] = useState<OutboxItem[]>([]);
  const [pullModalOpen, setPullModalOpen] = useState(false);
  const [pullImage, setPullImage] = useState('');
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [remoteItems, setRemoteItems] = useState<RemoteModelItem[]>([]);
  const [remoteLoading, setRemoteLoading] = useState(false);
  const [remoteRepo, setRemoteRepo] = useState('');
  const [pullingTag, setPullingTag] = useState<string | null>(null);

  useEffect(() => {
    setHealth(mockHealth);
    setModels(mockModels);
    setOutbox(mockOutbox);
  }, []);

  const refreshLocalModels = async () => {
    try {
      const list = await get<ModelInfo[]>('/models');
      setModels(list);
    } catch {
      // 后端未就绪时保持现有列表
    }
  };

  const handlePull = async () => {
    if (!pullImage.trim()) return;
    try {
      await post('/models/pull', { image: pullImage.trim() });
      message.success('拉取成功');
      setPullModalOpen(false);
      setPullImage('');
      await refreshLocalModels();
    } catch (e) {
      message.error((e as Error).message || '拉取失败');
    }
  };

  const fetchRemote = async (refresh = false) => {
    setRemoteLoading(true);
    try {
      const params: Record<string, string> = {};
      if (refresh) params.refresh = '1';
      if (remoteRepo) params.repo = remoteRepo;
      const data = await get<{ registry: string; repository: string; items: RemoteModelItem[] }>('/models/remote', params);
      setRemoteItems(data.items);
    } catch (e) {
      message.error((e as Error).message || '获取远端列表失败');
    } finally {
      setRemoteLoading(false);
    }
  };

  const openRemote = () => {
    setRemoteOpen(true);
    fetchRemote(true);
  };

  const pullRemote = async (item: RemoteModelItem) => {
    setPullingTag(item.tag);
    try {
      await post('/models/pull', { image: item.image });
      message.success(`拉取成功：${item.model_ref ?? item.tag}`);
      await refreshLocalModels();
      await fetchRemote(true);
    } catch (e) {
      message.error((e as Error).message || '拉取失败');
    } finally {
      setPullingTag(null);
    }
  };

  const handleDelete = (modelRef: string) => {
    setModels(prev => prev.filter(m => m.model_ref !== modelRef));
    message.success('模型已删除（mock）');
  };

  const handlePreload = (modelRef: string) => {
    message.info(`预加载模型: ${modelRef}（mock）`);
  };

  const handleRetryAll = () => {
    // TODO: POST /system/outbox/retry-all
    setOutbox(prev => prev.map(o => (o.status === 'dead' ? { ...o, status: 'pending', last_error: undefined } : o)));
    message.success('已触发全部死信重推（mock）');
  };

  const handleRetryOne = (id: number) => {
    // TODO: POST /system/outbox/{id}/retry
    setOutbox(prev => prev.map(o => (o.id === id ? { ...o, status: 'pending', last_error: undefined } : o)));
    message.success(`已重推回传记录 #${id}（mock）`);
  };

  const handleExportDead = () => {
    // TODO: 本地导出 dead 记录（跨平台契约 §3.5：dead 支持本地导出）
    message.info('导出死信记录（mock）');
  };

  const modelColumns = [
    { title: '模型引用', dataIndex: 'model_ref', key: 'model_ref', width: 130 },
    { title: '任务类型', dataIndex: 'skillname', key: 'skillname', width: 130 },
    { title: '精度', dataIndex: 'precision', key: 'precision', width: 60 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => {
        const colors: Record<string, string> = { ready: 'green', active: 'blue', pulling: 'processing', failed: 'red' };
        return <Tag color={colors[v]}>{v}</Tag>;
      },
    },
    { title: '类别数', dataIndex: 'classes', key: 'classes', width: 70, render: (c: string[]) => c.length },
    {
      title: '拉取时间', dataIndex: 'received_at', key: 'received_at', width: 170,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: '操作', key: 'action', width: 180,
      render: (_: unknown, record: ModelInfo) => (
        <Space>
          <a onClick={() => handlePreload(record.model_ref)}><ThunderboltOutlined /> 预加载</a>
          <a onClick={() => handleDelete(record.model_ref)} style={{ color: '#ff4d4f' }}><DeleteOutlined /> 删除</a>
        </Space>
      ),
    },
  ];

  const remoteColumns = [
    { title: 'Tag', dataIndex: 'tag', key: 'tag' },
    { title: '模型引用', dataIndex: 'model_ref', key: 'model_ref', render: (v: string | null) => v ?? '-' },
    { title: '精度', dataIndex: 'precision', key: 'precision', width: 70 },
    {
      title: '状态', key: 'local', width: 100,
      render: (_: unknown, r: RemoteModelItem) =>
        r.local ? <Tag color="green">已就绪</Tag> : <Tag>远端</Tag>,
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, r: RemoteModelItem) =>
        r.local ? (
          <Button size="small" disabled>已就绪</Button>
        ) : (
          <Button size="small" type="primary" loading={pullingTag === r.tag} onClick={() => pullRemote(r)}>拉取</Button>
        ),
    },
  ];

  const outboxStatusColors: Record<string, string> = {
    pending: 'blue',
    pushing: 'processing',
    pushed: 'green',
    dead: 'red',
  };

  const outboxColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '类型', dataIndex: 'kind', key: 'kind', width: 90, render: (v: string) => <Tag>{v}</Tag> },
    { title: '幂等键', dataIndex: 'idempotency_key', key: 'idempotency_key' },
    { title: '次数', dataIndex: 'attempts', key: 'attempts', width: 60 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => <Tag color={outboxStatusColors[v]}>{v}</Tag>,
    },
    { title: '下次重试', dataIndex: 'next_retry_at', key: 'next_retry_at', width: 170, render: (v?: string) => v ?? '-' },
    { title: '最后错误', dataIndex: 'last_error', key: 'last_error', render: (v?: string) => v ?? '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (v: string) => new Date(v).toLocaleString() },
    {
      title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: OutboxItem) =>
        record.status === 'dead' ? <a onClick={() => handleRetryOne(record.id)}><ReloadOutlined /> 重推</a> : null,
    },
  ];

  return (
    <div>
      <div className="page-header">
        <Typography.Title level={4}>系统</Typography.Title>
      </div>

      {/* 健康检查 */}
      {health && (
        <Card title="服务健康" size="small" style={{ marginBottom: 16 }}>
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={6}>
              <Statistic title="服务状态" value={health.status}
                valueStyle={{ color: health.status === 'UP' ? '#52c41a' : '#ff4d4f', fontSize: 20 }} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="GPU 显存" value={`${health.gpu.mem_used_gb}/${health.gpu.mem_total_gb} GB`} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="磁盘使用" value={`${health.disk.used_pct}%`}
                prefix={health.disk.used_pct > 80 ? <WarningOutlined style={{ color: '#ff4d4f' }} /> : <CheckCircleOutlined style={{ color: '#52c41a' }} />} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="推理队列" value={health.inspect.queue} suffix={`/ ${health.inspect.concurrency}`} />
            </Col>
          </Row>
          <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
            <Col xs={12} sm={6}>
              <Statistic title="工位" value={`${health.stations.online}/${health.stations.total} 在线`} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="已加载模型" value={health.models.length} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="Outbox待回传" value={health.outbox.pending}
                valueStyle={{ color: health.outbox.pending > 0 ? '#faad14' : undefined }} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="Outbox死信" value={health.outbox.dead}
                valueStyle={{ color: health.outbox.dead > 0 ? '#ff4d4f' : undefined }} />
            </Col>
          </Row>
        </Card>
      )}

      {/* 模型库 */}
      <Card
        title="模型库"
        size="small"
        extra={
          <Space>
            <Button icon={<CloudDownloadOutlined />} type="primary" onClick={openRemote}>远端模型</Button>
            <Button icon={<CloudDownloadOutlined />} onClick={() => setPullModalOpen(true)}>拉取模型</Button>
            <Button icon={<UploadOutlined />}>离线导入</Button>
          </Space>
        }
      >
        <Table
          columns={modelColumns}
          dataSource={models}
          rowKey="model_ref"
          size="small"
          pagination={false}
        />
      </Card>

      {/* Outbox 回传队列 */}
      <Card
        title="回传队列 (Outbox)"
        size="small"
        style={{ marginTop: 16 }}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} size="small" onClick={handleRetryAll}>全部重推</Button>
            <Button icon={<ExportOutlined />} size="small" onClick={handleExportDead}>导出死信</Button>
          </Space>
        }
      >
        <Table
          columns={outboxColumns}
          dataSource={outbox}
          rowKey="id"
          size="small"
          pagination={false}
        />
      </Card>

      {/* 版本信息 */}
      <Card title="版本信息" size="small" style={{ marginTop: 16 }}>
        <Descriptions column={3} size="small">
          <Descriptions.Item label="平台版本">0.1.0</Descriptions.Item>
          <Descriptions.Item label="skillname">0.1.0</Descriptions.Item>
          <Descriptions.Item label="pipeline-core">0.1.0</Descriptions.Item>
          <Descriptions.Item label="ONNX Runtime">1.18.0</Descriptions.Item>
          <Descriptions.Item label="SQLite">3.45.0</Descriptions.Item>
          <Descriptions.Item label="Python">3.11</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 拉取模型弹窗 */}
      <Modal
        title="拉取模型镜像"
        open={pullModalOpen}
        onOk={handlePull}
        onCancel={() => setPullModalOpen(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>输入镜像地址（Registry v2）：</Typography.Text>
          <Input
            placeholder="docker.io/corp/aoi-model:3-yolo-ds1"
            value={pullImage}
            onChange={(e) => setPullImage(e.target.value)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            支持 Docker Hub 和内网 registry。B 用只读凭据拉取，无需 Docker daemon。
          </Typography.Text>
        </Space>
      </Modal>

      {/* 远端模型列表弹窗（一键拉取） */}
      <Modal
        title="远端模型（一键拉取）"
        open={remoteOpen}
        onCancel={() => setRemoteOpen(false)}
        footer={null}
        width={640}
      >
        <Space style={{ marginBottom: 12 }}>
          <Input
            placeholder="仓库名（默认 MODEL_IMAGE_REPO）"
            value={remoteRepo}
            onChange={(e) => setRemoteRepo(e.target.value)}
            style={{ width: 280 }}
          />
          <Button icon={<ReloadOutlined />} loading={remoteLoading} onClick={() => fetchRemote(true)}>刷新</Button>
        </Space>
        <Table
          columns={remoteColumns}
          dataSource={remoteItems}
          rowKey="tag"
          size="small"
          pagination={false}
          loading={remoteLoading}
          locale={{ emptyText: '远端暂无可用模型' }}
        />
      </Modal>
    </div>
  );
}