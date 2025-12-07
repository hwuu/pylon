<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getConfig } from '../api/config'
import { getPolicy, updatePolicy, exportPolicy, importPolicy, confirmImportPolicy } from '../api/policy'

const configData = ref(null)
const policyData = ref(null)
const loading = ref(false)
const saving = ref(false)

// Import dialog
const importDialogVisible = ref(false)
const importDiff = ref(null)
const importLoading = ref(false)

// Edit mode
const editingKey = ref(null)
const editingValue = ref(null)

const loadData = async () => {
  loading.value = true
  try {
    const [configRes, policyRes] = await Promise.all([
      getConfig(),
      getPolicy()
    ])
    configData.value = configRes.data
    policyData.value = policyRes.data.policies
  } catch (error) {
    ElMessage.error('Failed to load configuration')
  } finally {
    loading.value = false
  }
}

const formatPolicyKey = (key) => {
  // Convert "rate_limit.global" to "Rate Limit > Global"
  return key
    .split('.')
    .map(part => part.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '))
    .join(' > ')
}

const formatPolicyValue = (value) => {
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}

const startEdit = (key, value) => {
  editingKey.value = key
  editingValue.value = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}

const cancelEdit = () => {
  editingKey.value = null
  editingValue.value = null
}

const saveEdit = async () => {
  if (!editingKey.value) return

  saving.value = true
  try {
    let parsedValue = editingValue.value
    // Try to parse as JSON if it looks like JSON
    if (editingValue.value.trim().startsWith('{') || editingValue.value.trim().startsWith('[')) {
      try {
        parsedValue = JSON.parse(editingValue.value)
      } catch {
        ElMessage.error('Invalid JSON format')
        saving.value = false
        return
      }
    } else if (!isNaN(Number(editingValue.value))) {
      parsedValue = Number(editingValue.value)
    }

    await updatePolicy(editingKey.value, parsedValue)
    policyData.value[editingKey.value] = parsedValue
    ElMessage.success('Policy updated successfully')
    cancelEdit()
  } catch (error) {
    ElMessage.error('Failed to update policy')
  } finally {
    saving.value = false
  }
}

const handleExport = async () => {
  try {
    const response = await exportPolicy()
    const blob = new Blob([response.data], { type: 'application/x-yaml' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'policy.yaml'
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('Policy exported')
  } catch (error) {
    ElMessage.error('Failed to export policy')
  }
}

const handleImportFile = async (uploadFile) => {
  importLoading.value = true
  try {
    const response = await importPolicy(uploadFile.raw)
    importDiff.value = response.data
    importDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail?.message || 'Failed to parse import file')
  } finally {
    importLoading.value = false
  }
  return false // Prevent default upload
}

const confirmImport = async () => {
  importLoading.value = true
  try {
    await confirmImportPolicy({
      added: importDiff.value.added,
      modified: importDiff.value.modified
    })
    ElMessage.success('Policy imported successfully')
    importDialogVisible.value = false
    importDiff.value = null
    await loadData()
  } catch (error) {
    ElMessage.error('Failed to import policy')
  } finally {
    importLoading.value = false
  }
}

const hasChanges = computed(() => {
  if (!importDiff.value) return false
  return Object.keys(importDiff.value.added).length > 0 ||
         Object.keys(importDiff.value.modified).length > 0
})

onMounted(loadData)
</script>

<template>
  <div class="settings-page">
    <!-- Header -->
    <div class="page-header">
      <h1>Settings</h1>
      <div class="header-actions">
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          accept=".yaml,.yml"
          :on-change="handleImportFile"
          :loading="importLoading"
        >
          <el-button :icon="Upload" :loading="importLoading">Import</el-button>
        </el-upload>
        <el-button :icon="Download" @click="handleExport">Export</el-button>
        <el-button
          :icon="Refresh"
          circle
          @click="loadData"
          :loading="loading"
        />
      </div>
    </div>

    <div v-loading="loading">
      <!-- Static Config (Read-only) -->
      <el-card class="config-card" v-if="configData">
        <template #header>
          <div class="card-header">
            <el-icon><Lock /></el-icon>
            <span>Static Configuration</span>
            <el-tag size="small" type="info">Read-only (requires restart)</el-tag>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Host">{{ configData.server.host }}</el-descriptions-item>
          <el-descriptions-item label="Proxy Port">{{ configData.server.proxy_port }}</el-descriptions-item>
          <el-descriptions-item label="Admin Port">{{ configData.server.admin_port }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- Dynamic Policy (Editable) -->
      <el-card class="config-card" v-if="policyData">
        <template #header>
          <div class="card-header">
            <el-icon><Setting /></el-icon>
            <span>Policy Configuration</span>
            <el-tag size="small" type="success">Hot-reload</el-tag>
          </div>
        </template>

        <el-table :data="Object.entries(policyData).map(([k, v]) => ({ key: k, value: v }))" style="width: 100%">
          <el-table-column prop="key" label="Key" width="280">
            <template #default="{ row }">
              <code>{{ row.key }}</code>
            </template>
          </el-table-column>
          <el-table-column label="Value">
            <template #default="{ row }">
              <div v-if="editingKey === row.key" class="edit-cell">
                <el-input
                  v-model="editingValue"
                  type="textarea"
                  :autosize="{ minRows: 1, maxRows: 10 }"
                  style="flex: 1"
                />
                <div class="edit-actions">
                  <el-button type="primary" size="small" @click="saveEdit" :loading="saving">Save</el-button>
                  <el-button size="small" @click="cancelEdit">Cancel</el-button>
                </div>
              </div>
              <div v-else class="value-cell" @click="startEdit(row.key, row.value)">
                <pre class="value-display">{{ formatPolicyValue(row.value) }}</pre>
                <el-icon class="edit-icon"><Edit /></el-icon>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <!-- Import Diff Dialog -->
    <el-dialog
      v-model="importDialogVisible"
      title="Import Policy - Review Changes"
      width="700px"
    >
      <div v-if="importDiff">
        <!-- Added -->
        <div v-if="Object.keys(importDiff.added).length > 0" class="diff-section">
          <h4><el-tag type="success">Added</el-tag></h4>
          <div v-for="(value, key) in importDiff.added" :key="key" class="diff-item">
            <code>{{ key }}</code>: <pre>{{ formatPolicyValue(value) }}</pre>
          </div>
        </div>

        <!-- Modified -->
        <div v-if="Object.keys(importDiff.modified).length > 0" class="diff-section">
          <h4><el-tag type="warning">Modified</el-tag></h4>
          <div v-for="(diff, key) in importDiff.modified" :key="key" class="diff-item">
            <code>{{ key }}</code>:
            <div class="diff-values">
              <div class="old-value">
                <span class="label">Old:</span>
                <pre>{{ formatPolicyValue(diff.old) }}</pre>
              </div>
              <div class="new-value">
                <span class="label">New:</span>
                <pre>{{ formatPolicyValue(diff.new) }}</pre>
              </div>
            </div>
          </div>
        </div>

        <!-- Unchanged -->
        <div v-if="Object.keys(importDiff.unchanged).length > 0" class="diff-section">
          <h4><el-tag type="info">Unchanged ({{ Object.keys(importDiff.unchanged).length }} items)</el-tag></h4>
        </div>

        <el-alert
          v-if="!hasChanges"
          type="info"
          :closable="false"
          show-icon
        >
          No changes detected in the imported file.
        </el-alert>
      </div>

      <template #footer>
        <el-button @click="importDialogVisible = false">Cancel</el-button>
        <el-button
          type="primary"
          @click="confirmImport"
          :loading="importLoading"
          :disabled="!hasChanges"
        >
          Confirm Import
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h1 {
  font-size: 24px;
  color: #303133;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.config-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.card-header .el-tag {
  margin-left: auto;
}

.value-cell {
  display: flex;
  align-items: flex-start;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.value-cell:hover {
  background-color: #f5f7fa;
}

.value-cell:hover .edit-icon {
  opacity: 1;
}

.value-display {
  margin: 0;
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  flex: 1;
}

.edit-icon {
  opacity: 0;
  margin-left: 8px;
  color: #409eff;
  transition: opacity 0.2s;
}

.edit-cell {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.edit-actions {
  display: flex;
  gap: 8px;
}

.diff-section {
  margin-bottom: 20px;
}

.diff-section h4 {
  margin: 0 0 10px 0;
}

.diff-item {
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 8px;
}

.diff-item code {
  font-weight: bold;
  color: #303133;
}

.diff-item pre {
  margin: 8px 0 0 0;
  font-size: 12px;
  background: white;
  padding: 8px;
  border-radius: 4px;
}

.diff-values {
  display: flex;
  gap: 16px;
  margin-top: 8px;
}

.old-value, .new-value {
  flex: 1;
}

.old-value .label {
  color: #f56c6c;
  font-weight: bold;
}

.new-value .label {
  color: #67c23a;
  font-weight: bold;
}
</style>
