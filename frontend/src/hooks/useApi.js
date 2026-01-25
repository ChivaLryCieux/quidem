/**
 * API调用自定义Hook
 */
import { useState, useCallback } from 'react';
import { message } from 'antd';

export const useApi = (apiFunction) => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [data, setData] = useState(null);

    const execute = useCallback(
        async (...args) => {
            setLoading(true);
            setError(null);

            try {
                const result = await apiFunction(...args);
                setData(result);
                return result;
            } catch (err) {
                setError(err.message);
                message.error(err.message);
                throw err;
            } finally {
                setLoading(false);
            }
        },
        [apiFunction]
    );

    return { loading, error, data, execute };
};
