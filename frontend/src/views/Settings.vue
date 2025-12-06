<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getConfig } from '../api/config'

const configData = ref(null)
const loading = ref(false)

const loadConfig = async () => {
  loading.value = true
  try {
    const response = await getConfig()
    configData.value = response.data
  } catch (error) {
    ElMessage.error('Failed to load configuration')
  } finally {
    loading.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <div class="settings-page">
    <!-- Header -->
    <div class="page-header">
      <h1>Settings</h1>
      <el-button
        :icon="Refresh"
        circle
        @click="loadConfig"
        :loading="loading"
      />
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 20px"
    >
      These settings are read-only and loaded from config.yaml. Restart the server after modifying the config file.
    </el-alert>

    <div v-loading="loading">
      <el-row :gutter="20" v-if="configData">
        <!-- Server Settings -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><Setting /></el-icon>
                <span>Server</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Host">
                {{ configData.server.host }}
              </el-descriptions-item>
              <el-descriptions-item label="Proxy Port">
                {{ configData.server.proxy_port }}
              </el-descriptions-item>
              <el-descriptions-item label="Admin Port">
                {{ configData.server.admin_port }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- Downstream Settings -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><Link /></el-icon>
                <span>Downstream API</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Base URL">
                <code>{{ configData.downstream.base_url }}</code>
              </el-descriptions-item>
              <el-descriptions-item label="Timeout">
                {{ configData.downstream.timeout }} seconds
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- Global Rate Limits -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><Odometer /></el-icon>
                <span>Global Rate Limits</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Max Concurrent">
                {{ configData.rate_limit.global.max_concurrent }}
              </el-descriptions-item>
              <el-descriptions-item label="Max Requests/min">
                {{ configData.rate_limit.global.max_requests_per_minute }}
              </el-descriptions-item>
              <el-descriptions-item label="Max SSE Connections">
                {{ configData.rate_limit.global.max_sse_connections }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- Default User Limits -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><User /></el-icon>
                <span>Default User Limits</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Max Concurrent">
                {{ configData.rate_limit.default_user.max_concurrent }}
              </el-descriptions-item>
              <el-descriptions-item label="Max Requests/min">
                {{ configData.rate_limit.default_user.max_requests_per_minute }}
              </el-descriptions-item>
              <el-descriptions-item label="Max SSE Connections">
                {{ configData.rate_limit.default_user.max_sse_connections }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- Queue Settings -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><List /></el-icon>
                <span>Queue</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Max Size">
                {{ configData.queue.max_size }}
              </el-descriptions-item>
              <el-descriptions-item label="Timeout">
                {{ configData.queue.timeout }} seconds
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- SSE Settings -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><VideoPlay /></el-icon>
                <span>SSE (Streaming)</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Idle Timeout">
                {{ configData.sse.idle_timeout }} seconds
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- Data Retention -->
        <el-col :span="12">
          <el-card class="settings-card">
            <template #header>
              <div class="card-header">
                <el-icon><Calendar /></el-icon>
                <span>Data Retention</span>
              </div>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Retention Period">
                {{ configData.data_retention.days }} days
              </el-descriptions-item>
              <el-descriptions-item label="Cleanup Interval">
                {{ configData.data_retention.cleanup_interval_hours }} hours
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>
    </div>
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

.settings-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.settings-card code {
  font-size: 13px;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
