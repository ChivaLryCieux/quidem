/**
 * 控制面板组件
 */
import React, { useState } from 'react';
import { Card, Button, Space, Modal, message } from 'antd';
import {
    PlayCircleOutlined,
    PauseCircleOutlined,
    StopOutlined,
    CloseCircleOutlined,
} from '@ant-design/icons';
import { controlAPI } from '../api/control';
import { useApi } from '../hooks/useApi';

const ControlPanel = () => {
    const [modalVisible, setModalVisible] = useState(false);
    const [currentAction, setCurrentAction] = useState(null);

    const { loading, execute } = useApi(controlAPI.sendCommand);

    const handleAction = async (action, actionName) => {
        setCurrentAction({ action, actionName });
        setModalVisible(true);
    };

    const confirmAction = async () => {
        try {
            await execute(currentAction.action);
            message.success(`${currentAction.actionName}命令已发送`);
            setModalVisible(false);
        } catch (error) {
            // 错误已在useApi中处理
        }
    };

    return (
        <Card title="交易控制">
            <Space size="large" wrap>
                <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    size="large"
                    loading={loading}
                    onClick={() => handleAction('start', '启动交易')}
                >
                    启动交易
                </Button>

                <Button
                    icon={<PauseCircleOutlined />}
                    size="large"
                    loading={loading}
                    onClick={() => handleAction('pause', '暂停交易')}
                >
                    暂停交易
                </Button>

                <Button
                    danger
                    icon={<StopOutlined />}
                    size="large"
                    loading={loading}
                    onClick={() => handleAction('stop', '停止交易')}
                >
                    停止交易
                </Button>

                <Button
                    danger
                    type="primary"
                    icon={<CloseCircleOutlined />}
                    size="large"
                    loading={loading}
                    onClick={() => handleAction('close_position', '强制平仓')}
                >
                    强制平仓
                </Button>
            </Space>

            <Modal
                title="确认操作"
                open={modalVisible}
                onOk={confirmAction}
                onCancel={() => setModalVisible(false)}
                okText="确认"
                cancelText="取消"
                confirmLoading={loading}
            >
                <p>确定要执行 <strong>{currentAction?.actionName}</strong> 操作吗?</p>
            </Modal>
        </Card>
    );
};

export default ControlPanel;
