<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMonitorData } from '../api/monitor'

const monitorData = ref({
  global_concurrent: 0,
  global_sse_connections: 0,
  global_requests_this_minute: 0,
  queue_size: 0
})

const loading = ref(false)
const autoRefresh = ref(true)
let refreshInterval = null

const loadMonitorData = async () => {
  try {
    const response = await getMonitorData()
    monitorData.value = response.data
  } catch (error) {
    ElMessage.error('Failed to load monitor data')
  }
}

const startAutoRefresh = () => {
  if (refreshInterval) clearInterval(refreshInterval)
  refreshInterval = setInterval(loadMonitorData, 2000)
}

const stopAutoRefresh = () => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

const toggleAutoRefresh = (value) => {
  if (value) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

onMounted(() => {
  loadMonitorData()
  if (autoRefresh.value) {
    startAutoRefresh()
  }
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="monitor-page">
    <!-- Header -->
    <div class="page-header">
      <h1>Real-time Monitor</h1>
      <div class="header-actions">
        <el-switch
          v-model="autoRefresh"
          active-text="Auto Refresh"
          @change="toggleAutoRefresh"
        />
        <el-button
          :icon="Refresh"
          circle
          @click="loadMonitorData"
          :loading="loading"
        />
      </div>
    </div>

    <!-- Monitor Cards -->
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card shadow="hover" class="monitor-card">
          <div class="card-icon concurrent">
            <el-icon size="32"><Connection /></el-icon>
          </div>
          <div class="card-content">
            <div class="card-value">{{ monitorData.global_concurrent }}</div>
            <div class="card-label">Active Connections</div>
            <div class="card-desc">Current concurrent requests</div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="6">
        <el-card shadow="hover" class="monitor-card">
          <div class="card-icon sse">
            <el-icon size="32"><VideoPlay /></el-icon>
          </div>
          <div class="card-content">
            <div class="card-value">{{ monitorData.global_sse_connections }}</div>
            <div class="card-label">SSE Connections</div>
            <div class="card-desc">Active streaming connections</div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="6">
        <el-card shadow="hover" class="monitor-card">
          <div class="card-icon requests">
            <el-icon size="32"><Odometer /></el-icon>
          </div>
          <div class="card-content">
            <div class="card-value">{{ monitorData.global_requests_this_minute }}</div>
            <div class="card-label">Requests / min</div>
            <div class="card-desc">Requests in current minute</div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="6">
        <el-card shadow="hover" class="monitor-card">
          <div class="card-icon queue">
            <el-icon size="32"><List /></el-icon>
          </div>
          <div class="card-content">
            <div class="card-value">{{ monitorData.queue_size }}</div>
            <div class="card-label">Queue Size</div>
            <div class="card-desc">Requests waiting in queue</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Status Indicators -->
    <el-card class="status-card">
      <template #header>
        <span>System Status</span>
      </template>

      <el-row :gutter="40">
        <el-col :span="8">
          <div class="status-item">
            <span class="status-label">Concurrent Load</span>
            <el-progress
              :percentage="Math.min((monitorData.global_concurrent / 50) * 100, 100)"
              :color="getProgressColor(monitorData.global_concurrent, 50)"
            />
          </div>
        </el-col>

        <el-col :span="8">
          <div class="status-item">
            <span class="status-label">SSE Load</span>
            <el-progress
              :percentage="Math.min((monitorData.global_sse_connections / 20) * 100, 100)"
              :color="getProgressColor(monitorData.global_sse_connections, 20)"
            />
          </div>
        </el-col>

        <el-col :span="8">
          <div class="status-item">
            <span class="status-label">Queue Load</span>
            <el-progress
              :percentage="Math.min((monitorData.queue_size / 100) * 100, 100)"
              :color="getProgressColor(monitorData.queue_size, 100)"
            />
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- Info Card -->
    <el-card>
      <template #header>
        <span>Monitor Info</span>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="Refresh Interval">2 seconds</el-descriptions-item>
        <el-descriptions-item label="Auto Refresh">
          <el-tag :type="autoRefresh ? 'success' : 'info'">
            {{ autoRefresh ? 'Enabled' : 'Disabled' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="Max Concurrent">50 (configurable)</el-descriptions-item>
        <el-descriptions-item label="Max SSE Connections">20 (configurable)</el-descriptions-item>
        <el-descriptions-item label="Max Queue Size">100 (configurable)</el-descriptions-item>
        <el-descriptions-item label="Queue Timeout">30 seconds</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script>
export default {
  methods: {
    getProgressColor(value, max) {
      const ratio = value / max
      if (ratio < 0.5) return '#67c23a'
      if (ratio < 0.8) return '#e6a23c'
      return '#f56c6c'
    }
  }
}
</script>

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
  gap: 15px;
  align-items: center;
}

.monitor-card {
  margin-bottom: 20px;
}

.monitor-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 25px;
}

.card-icon {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.card-icon.concurrent { background: linear-gradient(135deg, #667eea, #764ba2); }
.card-icon.sse { background: linear-gradient(135deg, #f093fb, #f5576c); }
.card-icon.requests { background: linear-gradient(135deg, #4facfe, #00f2fe); }
.card-icon.queue { background: linear-gradient(135deg, #43e97b, #38f9d7); }

.card-content {
  flex: 1;
}

.card-value {
  font-size: 32px;
  font-weight: 600;
  color: #303133;
  line-height: 1;
}

.card-label {
  font-size: 16px;
  color: #606266;
  margin-top: 8px;
}

.card-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.status-card {
  margin-bottom: 20px;
}

.status-item {
  padding: 10px 0;
}

.status-label {
  display: block;
  margin-bottom: 10px;
  font-weight: 500;
  color: #606266;
}
</style>
