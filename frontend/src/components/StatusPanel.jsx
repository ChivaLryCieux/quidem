/**
 * 状态面板组件
 */
import React from 'react';
import { Card, Row, Col, Statistic, Tag, Space } from 'antd';
import {
    DollarOutlined,
    RiseOutlined,
    FallOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import useBotStore from '../store/useBotStore';

const StatusPanel = () => {
    const { status, isOnline } = useBotStore();

    if (!status) {
        return (
            <Card>
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <p>等待数据...</p>
                </div>
            </Card>
        );
    }

    const isProfitable = status.position_size > 0;
    const positionColor = status.position_size > 0 ? '#52c41a' : status.position_size < 0 ? '#f5222d' : '#8c8c8c';

    return (
        <Card
            title={
                <Space>
                    <span>实时状态</span>
                    <Tag color={isOnline ? 'success' : 'error'}>
                        {isOnline ? '在线' : '离线'}
                    </Tag>
                </Space>
            }
        >
            <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} md={6}>
                    <Statistic
                        title="账户余额"
                        value={status.balance}
                        precision={2}
                        prefix={<DollarOutlined />}
                        suffix="USDT"
                    />
                </Col>

                <Col xs={24} sm={12} md={6}>
                    <Statistic
                        title="当前价格"
                        value={status.price}
                        precision={4}
                        prefix="$"
                    />
                </Col>

                <Col xs={24} sm={12} md={6}>
                    <Statistic
                        title="持仓数量"
                        value={Math.abs(status.position_size)}
                        precision={2}
                        valueStyle={{ color: positionColor }}
                        prefix={status.position_size > 0 ? <RiseOutlined /> : status.position_size < 0 ? <FallOutlined /> : null}
                        suffix={status.position_size > 0 ? '多' : status.position_size < 0 ? '空' : '无'}
                    />
                </Col>

                <Col xs={24} sm={12} md={6}>
                    <Statistic
                        title="AI置信度"
                        value={status.ai_conf * 100}
                        precision={1}
                        suffix="%"
                        prefix={<ThunderboltOutlined />}
                    />
                </Col>
            </Row>

            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                <Col span={8}>
                    <Card size="small">
                        <Statistic
                            title="市场状态"
                            value={status.regime}
                            valueStyle={{ fontSize: 16 }}
                        />
                    </Card>
                </Col>

                <Col span={8}>
                    <Card size="small">
                        <Statistic
                            title="聚类状态"
                            value={status.cluster}
                            valueStyle={{ fontSize: 16 }}
                        />
                    </Card>
                </Col>

                <Col span={8}>
                    <Card size="small">
                        <Statistic
                            title="高频信号"
                            value={status.hf_signal}
                            precision={3}
                            valueStyle={{ fontSize: 16 }}
                        />
                    </Card>
                </Col>
            </Row>
        </Card>
    );
};

export default StatusPanel;
