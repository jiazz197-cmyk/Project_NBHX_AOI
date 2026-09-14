import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Typography } from 'antd';
import {
  DashboardOutlined,
  SearchOutlined,
  FileTextOutlined,
  EnvironmentOutlined,
  SettingOutlined,
} from '@ant-design/icons';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '概览' },
  { key: '/inspections', icon: <SearchOutlined />, label: '检测记录' },
  { key: '/reports', icon: <FileTextOutlined />, label: '日报' },
  { key: '/stations', icon: <EnvironmentOutlined />, label: '工位与相机' },
  { key: '/system', icon: <SettingOutlined />, label: '系统' },
];

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // 选中的菜单项：取当前路径匹配
  const selectedKey = '/' + (location.pathname.split('/')[1] || '');

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <div style={{ height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', borderBottom: '1px solid #f0f0f0' }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            {collapsed ? 'AOI' : 'AOI 推理检测'}
          </Typography.Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center' }}>
          <Typography.Text type="secondary">平台 B · 推理检测 · 无用户认证 · 内网访问</Typography.Text>
        </Header>
        <Content style={{ margin: 16, padding: 24, background: '#fff', borderRadius: 8, minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}