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
  CloseCircleOutlined, WarningOutlined, SyncOutlined,
} from '@ant-design/icons';
import { mockHealth, mockModels } from '../../api/mock';
import type { HealthData, ModelInfo } from '../../api/types';

export default function System() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [pullModalOpen, setPullModalOpen] = useState(false);
  const [pullImage, setPullImage] = useState('');

  useEffect(() => {
    setHealth(mockHealth);
    setModels(mockModels);
  }, []);

  const handlePull = () => {
    if (!pullImage.trim()) return;
    // TODO: POST /models/pull { image: "..." }
    message.info(`拉取模型: ${pullImage}（mock）`);
    setPullModalOpen(false);
    setPullImage('');
  };

  const handleDelete = (modelRef: string) => {
    setModels(prev => prev.filter(m => m.model_ref !== modelRef));
    message.success('模型已删除（mock）');
  };

  const handlePreload = (modelRef: string) => {
    message.info(`预加载模型: ${modelRef}（mock）`);
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
            <Button icon={<CloudDownloadOutlined />} type="primary" onClick={() => setPullModalOpen(true)}>
              拉取模型
            </Button>
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

      {/* Outbox 状态 */}
      {health && (
        <Card title="回传队列 (Outbox)" size="small" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic title="待回传" value={health.outbox.pending} valueStyle={{ color: '#1677ff' }} />
            </Col>
            <Col span={8}>
              <Statistic title="死信" value={health.outbox.dead} valueStyle={{ color: '#ff4d4f' }} />
            </Col>
            <Col span={8}>
              <Space>
                <Button icon={<ReloadOutlined />} size="small">全部重推</Button>
              </Space>
            </Col>
          </Row>
        </Card>
      )}

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
    </div>
  );
}