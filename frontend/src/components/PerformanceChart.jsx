/**
 * 收益图表组件
 */
import React, { useEffect, useState } from 'react';
import { Card } from 'antd';
import ReactECharts from 'echarts-for-react';
import { historyAPI } from '../api/history';

const PerformanceChart = () => {
    const [chartData, setChartData] = useState({ times: [], pnls: [] });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        try {
            const trades = await historyAPI.getTrades(50);

            const times = [];
            const pnls = [];
            let cumulative = 0;

            trades.forEach((trade) => {
                if (trade.pnl !== null && trade.pnl !== undefined) {
                    cumulative += trade.pnl;
                    times.push(new Date(trade.timestamp).toLocaleString());
                    pnls.push(cumulative.toFixed(2));
                }
            });

            setChartData({ times, pnls });
        } catch (error) {
            console.error('加载图表数据失败:', error);
        } finally {
            setLoading(false);
        }
    };

    const option = {
        backgroundColor: 'transparent',
        title: {
            text: '累计收益曲线',
            left: 'center',
            textStyle: {
                color: '#fff',
            },
        },
        tooltip: {
            trigger: 'axis',
            axisPointer: {
                type: 'cross',
            },
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '3%',
            containLabel: true,
        },
        xAxis: {
            type: 'category',
            data: chartData.times,
            axisLabel: {
                color: '#8c8c8c',
                rotate: 45,
            },
        },
        yAxis: {
            type: 'value',
            axisLabel: {
                color: '#8c8c8c',
                formatter: '{value} USDT',
            },
            splitLine: {
                lineStyle: {
                    color: '#2f2f2f',
                },
            },
        },
        series: [
            {
                name: '累计盈亏',
                type: 'line',
                data: chartData.pnls,
                smooth: true,
                lineStyle: {
                    width: 2,
                    color: '#1890ff',
                },
                areaStyle: {
                    color: {
                        type: 'linear',
                        x: 0,
                        y: 0,
                        x2: 0,
                        y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(24, 144, 255, 0.3)' },
                            { offset: 1, color: 'rgba(24, 144, 255, 0.05)' },
                        ],
                    },
                },
            },
        ],
    };

    return (
        <Card loading={loading}>
            <ReactECharts option={option} style={{ height: '400px' }} />
        </Card>
    );
};

export default PerformanceChart;
