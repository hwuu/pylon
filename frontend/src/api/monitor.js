import api from './index'

export const getMonitorData = () => {
  return api.get('/monitor')
}
