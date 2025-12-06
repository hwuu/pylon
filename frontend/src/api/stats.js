import api from './index'

export const getStatsSummary = (params = {}) => {
  return api.get('/stats/summary', { params })
}

export const getUsersStats = (params = {}) => {
  return api.get('/stats/users', { params })
}

export const getUserStats = (apiKeyId, params = {}) => {
  return api.get(`/stats/users/${apiKeyId}`, { params })
}

export const getApisStats = (params = {}) => {
  return api.get('/stats/apis', { params })
}

export const getApiStats = (apiIdentifier, params = {}) => {
  return api.get(`/stats/apis/${encodeURIComponent(apiIdentifier)}`, { params })
}

export const exportStats = (format = 'json', params = {}) => {
  return api.get('/stats/export', {
    params: { format, ...params },
    responseType: format === 'json' ? 'json' : 'blob'
  })
}
