/**
 * 历史记录页面
 */
import React, { useEffect, useState } from 'react';
import { Table, Card, Tag } from 'antd';
import { historyAPI } from '../api/history';

const History = () => {
    const [trades, setTrades] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadTrades();
    }, []);

    const loadTrades = async () => {
        try {
            const data = await historyAPI.getTrades(100);
            setTrades(data);
        } catch (error) {
            console.error('加载交易历史失败:', error);
        } finally {
            setLoading(false);
        }
    };

    const columns = [
        {
            title: '时间',
            dataIndex: 'timestamp',
            key: 'timestamp',
            render: (timestamp) => new Date(timestamp).toLocaleString(),
        },
        {
            title: '操作',
            dataIndex: 'action',
            key: 'action',
            render: (action) => {
                const color = action.includes('买') || action.includes('多') ? 'green' : 'red';
                return <Tag color={color}>{action}</Tag>;
            },
        },
        {
            title: '价格',
            dataIndex: 'price',
            key: 'price',
            render: (price) => `$${price.toFixed(4)}`,
        },
        {
            title: '数量',
            dataIndex: 'size',
            key: 'size',
            render: (size) => size.toFixed(2),
        },
        {
            title: '盈亏',
            dataIndex: 'pnl',
            key: 'pnl',
            render: (pnl) => {
                if (pnl === null || pnl === undefined) return '-';
                const color = pnl >= 0 ? '#52c41a' : '#f5222d';
                return <span style={{ color }}>{pnl.toFixed(2)} USDT</span>;
            },
        },
        {
            title: '余额',
            dataIndex: 'balance',
            key: 'balance',
            render: (balance) => `${balance.toFixed(2)} USDT`,
        },
    ];

    return (
        <div style={{ padding: '24px' }}>
            <Card title="交易历史">
                <Table
                    columns={columns}
                    dataSource={trades}
                    loading={loading}
                    rowKey="timestamp"
                    pagination={{ pageSize: 20 }}
                />
            </Card>
        </div>
    );
};

export default History;
