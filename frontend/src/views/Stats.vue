<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getStatsSummary,
  getUsersStats,
  getApisStats,
  exportStats
} from '../api/stats'

// State
const summary = ref({
  start_time: '',
  end_time: '',
  total_requests: 0,
  total_sse_messages: 0,
  total_count: 0,
  success_rate: 0,
  avg_response_time_ms: 0,
  sse_connections: 0,
  rate_limited_count: 0
})

const usersStats = ref([])
const apisStats = ref([])
const loading = ref(false)
const activeTab = ref('summary')

// Time range filter
const timeRange = ref('7d')
const customRange = ref([])

const timeRangeOptions = [
  { label: 'Last 24 Hours', value: '1d' },
  { label: 'Last 7 Days', value: '7d' },
  { label: 'Last 30 Days', value: '30d' },
  { label: 'Custom', value: 'custom' }
]

// Compute time range params
const getTimeParams = () => {
  const now = new Date()
  let start_time, end_time

  if (timeRange.value === 'custom' && customRange.value?.length === 2) {
    start_time = customRange.value[0].toISOString()
    end_time = customRange.value[1].toISOString()
  } else {
    end_time = now.toISOString()
    const days = timeRange.value === '1d' ? 1 : timeRange.value === '30d' ? 30 : 7
    start_time = new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString()
  }

  return { start_time, end_time }
}

// Load data
const loadStats = async () => {
  loading.value = true
  try {
    const params = getTimeParams()
    const [summaryRes, usersRes, apisRes] = await Promise.all([
      getStatsSummary(params),
      getUsersStats(params),
      getApisStats(params)
    ])
    summary.value = summaryRes.data
    usersStats.value = usersRes.data
    apisStats.value = apisRes.data
  } catch (error) {
    ElMessage.error('Failed to load statistics')
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)

// Export
const handleExport = async (format) => {
  try {
    const params = getTimeParams()
    const response = await exportStats(format, params)

    if (format === 'json') {
      const blob = new Blob([JSON.stringify(response.data, null, 2)], { type: 'application/json' })
      downloadBlob(blob, `stats.${format}`)
    } else {
      downloadBlob(response.data, `stats.${format}`)
    }

    ElMessage.success(`Exported as ${format.toUpperCase()}`)
  } catch (error) {
    ElMessage.error('Export failed')
  }
}

const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// Format helpers
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

const formatNumber = (num) => {
  return num?.toLocaleString() ?? '0'
}

const formatMs = (ms) => {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}
</script>

<template>
  <div class="stats-page">
    <!-- Header -->
    <div class="page-header">
      <h1>Statistics</h1>
      <div class="header-actions">
        <el-select v-model="timeRange" @change="loadStats" style="width: 150px">
          <el-option
            v-for="opt in timeRangeOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <el-date-picker
          v-if="timeRange === 'custom'"
          v-model="customRange"
          type="datetimerange"
          range-separator="to"
          start-placeholder="Start"
          end-placeholder="End"
          @change="loadStats"
        />

        <el-dropdown @command="handleExport">
          <el-button type="primary">
            Export <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="json">JSON</el-dropdown-item>
              <el-dropdown-item command="csv">CSV</el-dropdown-item>
              <el-dropdown-item command="html">HTML</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-button :icon="Refresh" circle @click="loadStats" :loading="loading" />
      </div>
    </div>

    <!-- Summary Cards -->
    <el-row :gutter="20" class="summary-cards">
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="summary-card">
            <div class="summary-value">{{ formatNumber(summary.total_count) }}</div>
            <div class="summary-label">Total Requests</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="summary-card success">
            <div class="summary-value">{{ summary.success_rate }}%</div>
            <div class="summary-label">Success Rate</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="summary-card">
            <div class="summary-value">{{ formatMs(summary.avg_response_time_ms) }}</div>
            <div class="summary-label">Avg Response</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="summary-card">
            <div class="summary-value">{{ formatNumber(summary.sse_connections) }}</div>
            <div class="summary-label">SSE Connections</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="summary-card">
            <div class="summary-value">{{ formatNumber(summary.total_sse_messages) }}</div>
            <div class="summary-label">SSE Messages</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover">
          <div class="summary-card danger">
            <div class="summary-value">{{ formatNumber(summary.rate_limited_count) }}</div>
            <div class="summary-label">Rate Limited</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Tabs -->
    <el-card>
      <el-tabs v-model="activeTab">
        <!-- By User Tab -->
        <el-tab-pane label="By User" name="users">
          <el-table :data="usersStats" v-loading="loading" stripe>
            <el-table-column prop="api_key_id" label="API Key ID" width="320">
              <template #default="{ row }">
                <code>{{ row.api_key_id }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="total_count" label="Total Requests" width="130">
              <template #default="{ row }">
                {{ formatNumber(row.total_count) }}
              </template>
            </el-table-column>
            <el-table-column prop="success_rate" label="Success Rate" width="120">
              <template #default="{ row }">
                <el-tag :type="row.success_rate >= 95 ? 'success' : row.success_rate >= 80 ? 'warning' : 'danger'">
                  {{ row.success_rate }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="avg_response_time_ms" label="Avg Response" width="120">
              <template #default="{ row }">
                {{ formatMs(row.avg_response_time_ms) }}
              </template>
            </el-table-column>
            <el-table-column prop="sse_connections" label="SSE Conn" width="100">
              <template #default="{ row }">
                {{ formatNumber(row.sse_connections) }}
              </template>
            </el-table-column>
            <el-table-column prop="total_sse_messages" label="SSE Msgs" width="100">
              <template #default="{ row }">
                {{ formatNumber(row.total_sse_messages) }}
              </template>
            </el-table-column>
            <el-table-column prop="rate_limited_count" label="Rate Limited" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.rate_limited_count > 0" type="danger">
                  {{ formatNumber(row.rate_limited_count) }}
                </el-tag>
                <span v-else>0</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- By API Tab -->
        <el-tab-pane label="By API" name="apis">
          <el-table :data="apisStats" v-loading="loading" stripe>
            <el-table-column prop="api_identifier" label="API" min-width="200">
              <template #default="{ row }">
                <code>{{ row.api_identifier }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="total_count" label="Total Requests" width="130">
              <template #default="{ row }">
                {{ formatNumber(row.total_count) }}
              </template>
            </el-table-column>
            <el-table-column prop="success_rate" label="Success Rate" width="120">
              <template #default="{ row }">
                <el-tag :type="row.success_rate >= 95 ? 'success' : row.success_rate >= 80 ? 'warning' : 'danger'">
                  {{ row.success_rate }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="avg_response_time_ms" label="Avg Response" width="120">
              <template #default="{ row }">
                {{ formatMs(row.avg_response_time_ms) }}
              </template>
            </el-table-column>
            <el-table-column prop="sse_connections" label="SSE Conn" width="100">
              <template #default="{ row }">
                {{ formatNumber(row.sse_connections) }}
              </template>
            </el-table-column>
            <el-table-column prop="total_sse_messages" label="SSE Msgs" width="100">
              <template #default="{ row }">
                {{ formatNumber(row.total_sse_messages) }}
              </template>
            </el-table-column>
            <el-table-column prop="rate_limited_count" label="Rate Limited" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.rate_limited_count > 0" type="danger">
                  {{ formatNumber(row.rate_limited_count) }}
                </el-tag>
                <span v-else>0</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- Time Range Info -->
    <el-card class="info-card">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="Start Time">
          {{ formatDate(summary.start_time) }}
        </el-descriptions-item>
        <el-descriptions-item label="End Time">
          {{ formatDate(summary.end_time) }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
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

.summary-cards {
  margin-bottom: 20px;
}

.summary-card {
  text-align: center;
  padding: 10px 0;
}

.summary-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.summary-card.success .summary-value { color: #67c23a; }
.summary-card.danger .summary-value { color: #f56c6c; }

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.info-card {
  margin-top: 20px;
}
</style>
