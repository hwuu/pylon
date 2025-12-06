<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listApiKeys,
  createApiKey,
  revokeApiKey,
  refreshApiKey,
  deleteApiKey,
  getApiKeyCount
} from '../api/apiKeys'

// State
const apiKeys = ref([])
const counts = ref({ total: 0, active: 0, expired: 0, revoked: 0 })
const loading = ref(false)
const showCreateDialog = ref(false)
const showKeyDialog = ref(false)
const createdKey = ref('')

// Filters
const includeRevoked = ref(false)
const includeExpired = ref(false)

// Create form
const createForm = ref({
  description: '',
  priority: 'normal',
  expires_in_days: null
})

// Load data
const loadApiKeys = async () => {
  loading.value = true
  try {
    const [keysRes, countRes] = await Promise.all([
      listApiKeys({
        include_revoked: includeRevoked.value,
        include_expired: includeExpired.value
      }),
      getApiKeyCount()
    ])
    apiKeys.value = keysRes.data
    counts.value = countRes.data
  } catch (error) {
    ElMessage.error('Failed to load API keys')
  } finally {
    loading.value = false
  }
}

onMounted(loadApiKeys)

// Create API Key
const handleCreate = async () => {
  try {
    const data = {
      description: createForm.value.description,
      priority: createForm.value.priority
    }
    if (createForm.value.expires_in_days) {
      data.expires_in_days = parseInt(createForm.value.expires_in_days)
    }

    const response = await createApiKey(data)
    createdKey.value = response.data.key
    showCreateDialog.value = false
    showKeyDialog.value = true

    // Reset form
    createForm.value = { description: '', priority: 'normal', expires_in_days: null }

    await loadApiKeys()
    ElMessage.success('API Key created')
  } catch (error) {
    ElMessage.error('Failed to create API key')
  }
}

// Revoke API Key
const handleRevoke = async (row) => {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to revoke this API key? (${row.key_prefix}...)`,
      'Confirm Revoke',
      { type: 'warning' }
    )
    await revokeApiKey(row.id)
    await loadApiKeys()
    ElMessage.success('API Key revoked')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('Failed to revoke API key')
    }
  }
}

// Refresh API Key
const handleRefresh = async (row) => {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to refresh this API key? The old key will no longer work.`,
      'Confirm Refresh',
      { type: 'warning' }
    )
    const response = await refreshApiKey(row.id)
    createdKey.value = response.data.key
    showKeyDialog.value = true
    await loadApiKeys()
    ElMessage.success('API Key refreshed')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('Failed to refresh API key')
    }
  }
}

// Delete API Key
const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to permanently delete this API key?`,
      'Confirm Delete',
      { type: 'error' }
    )
    await deleteApiKey(row.id)
    await loadApiKeys()
    ElMessage.success('API Key deleted')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('Failed to delete API key')
    }
  }
}

// Copy key to clipboard
const copyKey = async () => {
  try {
    await navigator.clipboard.writeText(createdKey.value)
    ElMessage.success('Copied to clipboard')
  } catch {
    ElMessage.error('Failed to copy')
  }
}

// Format date
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

// Get status tag type
const getStatusType = (row) => {
  if (row.revoked_at) return 'danger'
  if (!row.is_valid) return 'warning'
  return 'success'
}

const getStatusText = (row) => {
  if (row.revoked_at) return 'Revoked'
  if (!row.is_valid) return 'Expired'
  return 'Active'
}

// Get priority tag type
const getPriorityType = (priority) => {
  switch (priority) {
    case 'high': return 'danger'
    case 'low': return 'info'
    default: return ''
  }
}
</script>

<template>
  <div class="api-keys-page">
    <!-- Header -->
    <div class="page-header">
      <h1>API Keys</h1>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        Create API Key
      </el-button>
    </div>

    <!-- Stats Cards -->
    <el-row :gutter="20" class="stats-cards">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value">{{ counts.total }}</div>
            <div class="stat-label">Total</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card success">
            <div class="stat-value">{{ counts.active }}</div>
            <div class="stat-label">Active</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card warning">
            <div class="stat-value">{{ counts.expired }}</div>
            <div class="stat-label">Expired</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card danger">
            <div class="stat-value">{{ counts.revoked }}</div>
            <div class="stat-label">Revoked</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Filters -->
    <el-card class="filter-card">
      <el-checkbox v-model="includeRevoked" @change="loadApiKeys">
        Show Revoked
      </el-checkbox>
      <el-checkbox v-model="includeExpired" @change="loadApiKeys">
        Show Expired
      </el-checkbox>
      <el-button
        :icon="Refresh"
        circle
        @click="loadApiKeys"
        :loading="loading"
        style="float: right"
      />
    </el-card>

    <!-- Table -->
    <el-card>
      <el-table :data="apiKeys" v-loading="loading" stripe>
        <el-table-column prop="key_prefix" label="Key Prefix" width="120">
          <template #default="{ row }">
            <code>{{ row.key_prefix }}...</code>
          </template>
        </el-table-column>

        <el-table-column prop="description" label="Description" min-width="150" />

        <el-table-column prop="priority" label="Priority" width="100">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)" size="small">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="Status" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row)" size="small">
              {{ getStatusText(row) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="Created" width="170">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column prop="expires_at" label="Expires" width="170">
          <template #default="{ row }">
            {{ formatDate(row.expires_at) }}
          </template>
        </el-table-column>

        <el-table-column label="Actions" width="200" fixed="right">
          <template #default="{ row }">
            <el-button-group v-if="row.is_valid">
              <el-button
                size="small"
                type="warning"
                @click="handleRefresh(row)"
              >
                Refresh
              </el-button>
              <el-button
                size="small"
                type="danger"
                @click="handleRevoke(row)"
              >
                Revoke
              </el-button>
            </el-button-group>
            <el-button
              v-else
              size="small"
              type="danger"
              @click="handleDelete(row)"
            >
              Delete
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create Dialog -->
    <el-dialog v-model="showCreateDialog" title="Create API Key" width="500">
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="Description">
          <el-input
            v-model="createForm.description"
            placeholder="Optional description"
          />
        </el-form-item>

        <el-form-item label="Priority">
          <el-select v-model="createForm.priority" style="width: 100%">
            <el-option label="High" value="high" />
            <el-option label="Normal" value="normal" />
            <el-option label="Low" value="low" />
          </el-select>
        </el-form-item>

        <el-form-item label="Expires In">
          <el-input
            v-model="createForm.expires_in_days"
            type="number"
            placeholder="Days (leave empty for never)"
          >
            <template #append>days</template>
          </el-input>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">Cancel</el-button>
        <el-button type="primary" @click="handleCreate">Create</el-button>
      </template>
    </el-dialog>

    <!-- Key Display Dialog -->
    <el-dialog
      v-model="showKeyDialog"
      title="API Key Created"
      width="550"
      :close-on-click-modal="false"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 20px"
      >
        Make sure to copy this API key now. You won't be able to see it again!
      </el-alert>

      <div class="key-display">
        <code>{{ createdKey }}</code>
        <el-button type="primary" @click="copyKey">
          <el-icon><CopyDocument /></el-icon>
          Copy
        </el-button>
      </div>

      <template #footer>
        <el-button type="primary" @click="showKeyDialog = false">
          Done
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

.stats-cards {
  margin-bottom: 20px;
}

.stat-card {
  text-align: center;
  padding: 10px 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
}

.stat-card.success .stat-value { color: #67c23a; }
.stat-card.warning .stat-value { color: #e6a23c; }
.stat-card.danger .stat-value { color: #f56c6c; }

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 4px;
}

.filter-card {
  margin-bottom: 20px;
}

.filter-card :deep(.el-card__body) {
  padding: 12px 20px;
}

.key-display {
  display: flex;
  gap: 10px;
  align-items: center;
  background: #f5f7fa;
  padding: 15px;
  border-radius: 4px;
}

.key-display code {
  flex: 1;
  font-size: 14px;
  word-break: break-all;
}
</style>
