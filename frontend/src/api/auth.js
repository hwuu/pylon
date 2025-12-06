import api from './index'

export const login = (password) => {
  return api.post('/login', { password })
}

export const checkHealth = () => {
  return api.get('/health')
}
