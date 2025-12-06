import api from './index'

export const listApiKeys = (params = {}) => {
  return api.get('/api-keys', { params })
}

export const createApiKey = (data) => {
  return api.post('/api-keys', data)
}

export const getApiKey = (id) => {
  return api.get(`/api-keys/${id}`)
}

export const updateApiKey = (id, data) => {
  return api.put(`/api-keys/${id}`, data)
}

export const revokeApiKey = (id) => {
  return api.post(`/api-keys/${id}/revoke`)
}

export const refreshApiKey = (id) => {
  return api.post(`/api-keys/${id}/refresh`)
}

export const deleteApiKey = (id) => {
  return api.delete(`/api-keys/${id}`)
}

export const getApiKeyCount = () => {
  return api.get('/api-keys/count')
}
