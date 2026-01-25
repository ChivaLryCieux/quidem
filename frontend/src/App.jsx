/**
 * 主应用组件
 */
import React from 'react';
import { Layout, Menu } from 'antd';
import {
    DashboardOutlined,
    HistoryOutlined,
} from '@ant-design/icons';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import History from './pages/History';
import './App.css';

const { Header, Content } = Layout;

const AppContent = () => {
    const location = useLocation();

    const menuItems = [
        {
            key: '/',
            icon: <DashboardOutlined />,
            label: <Link to="/">控制台</Link>,
        },
        {
            key: '/history',
            icon: <HistoryOutlined />,
            label: <Link to="/history">历史记录</Link>,
        },
    ];

    return (
        <Layout style={{ minHeight: '100vh' }}>
            <Header style={{ display: 'flex', alignItems: 'center' }}>
                <div style={{ color: '#fff', fontSize: '20px', fontWeight: 'bold', marginRight: '50px' }}>
                    Q-Bot 交易系统
                </div>
                <Menu
                    theme="dark"
                    mode="horizontal"
                    selectedKeys={[location.pathname]}
                    items={menuItems}
                    style={{ flex: 1, minWidth: 0 }}
                />
            </Header>

            <Content>
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/history" element={<History />} />
                </Routes>
            </Content>
        </Layout>
    );
};

function App() {
    return (
        <BrowserRouter>
            <AppContent />
        </BrowserRouter>
    );
}

export default App;
