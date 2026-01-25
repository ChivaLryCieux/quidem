/**
 * 主控制台页面
 */
import React, { useEffect } from 'react';
import { Row, Col, Card, Statistic } from 'antd';
import StatusPanel from '../components/StatusPanel';
import ControlPanel from '../components/ControlPanel';
import PerformanceChart from '../components/PerformanceChart';
import { useWebSocket } from '../hooks/useWebSocket';
import useBotStore from '../store/useBotStore';
import { historyAPI } from '../api/history';

const Dashboard = () => {
    useWebSocket(); // 启动WebSocket连接

    const { performance, setPerformance } = useBotStore();

    useEffect(() => {
        loadPerformance();

        // 每30秒刷新一次收益统计
        const interval = setInterval(loadPerformance, 30000);
        return () => clearInterval(interval);
    }, []);

    const loadPerformance = async () => {
        try {
            const stats = await historyAPI.getPerformance(100);
            setPerformance(stats);
        } catch (error) {
            console.error('加载收益统计失败:', error);
        }
    };

    return (
        <div style={{ padding: '24px' }}>
            <Row gutter={[16, 16]}>
                {/* 状态面板 */}
                <Col span={24}>
                    <StatusPanel />
                </Col>

                {/* 控制面板 */}
                <Col span={24}>
                    <ControlPanel />
                </Col>

                {/* 收益统计 */}
                {performance && (
                    <Col span={24}>
                        <Card title="收益统计">
                            <Row gutter={16}>
                                <Col xs={24} sm={12} md={6}>
                                    <Statistic
                                        title="总交易次数"
                                        value={performance.total_trades}
                                    />
                                </Col>
                                <Col xs={24} sm={12} md={6}>
                                    <Statistic
                                        title="胜率"
                                        value={performance.win_rate * 100}
                                        precision={1}
                                        suffix="%"
                                    />
                                </Col>
                                <Col xs={24} sm={12} md={6}>
                                    <Statistic
                                        title="总盈亏"
                                        value={performance.total_pnl}
                                        precision={2}
                                        suffix="USDT"
                                        valueStyle={{
                                            color: performance.total_pnl >= 0 ? '#52c41a' : '#f5222d',
                                        }}
                                    />
                                </Col>
                                <Col xs={24} sm={12} md={6}>
                                    <Statistic
                                        title="最大回撤"
                                        value={performance.max_drawdown}
                                        precision={2}
                                        suffix="USDT"
                                        valueStyle={{ color: '#f5222d' }}
                                    />
                                </Col>
                            </Row>
                        </Card>
                    </Col>
                )}

                {/* 收益图表 */}
                <Col span={24}>
                    <PerformanceChart />
                </Col>
            </Row>
        </div>
    );
};

export default Dashboard;
