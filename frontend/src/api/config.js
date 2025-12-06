import api from './index'

export const getConfig = () => {
  return api.get('/config')
}
