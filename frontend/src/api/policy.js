import api from './index'

// Get all policies
export function getPolicy() {
  return api.get('/policy')
}

// Get single policy
export function getPolicyItem(key) {
  return api.get(`/policy/${key}`)
}

// Update single policy
export function updatePolicy(key, value) {
  return api.put(`/policy/${key}`, { value })
}

// Export policy as YAML
export function exportPolicy() {
  return api.post('/policy/export', null, {
    responseType: 'blob'
  })
}

// Import policy (get diff preview)
export function importPolicy(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/policy/import', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

// Confirm policy import
export function confirmImportPolicy(changes) {
  return api.post('/policy/import/confirm', changes)
}
