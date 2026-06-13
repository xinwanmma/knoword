<template>
  <div class="status-page">
    <h2>系统状态</h2>
    <p class="subtitle">检查各服务组件的运行状态</p>

    <el-button type="primary" :loading="loading" @click="checkHealth" style="margin-bottom: 20px">
      <el-icon><Refresh /></el-icon> 刷新状态
    </el-button>

    <div class="status-grid">
      <div
        v-for="(ok, name) in services"
        :key="name"
        class="status-card"
        :class="ok ? 'status-ok' : 'status-error'"
      >
        <div class="status-icon">
          <el-icon v-if="ok" size="32" color="#67c23a"><CircleCheck /></el-icon>
          <el-icon v-else size="32" color="#f56c6c"><CircleClose /></el-icon>
        </div>
        <div class="status-info">
          <h4>{{ serviceLabels[name] || name }}</h4>
          <p>{{ ok ? '运行正常' : '连接失败' }}</p>
        </div>
      </div>
    </div>

    <div v-if="overallStatus" class="overall-status" :class="overallStatus === 'ok' ? 'overall-ok' : 'overall-degraded'">
      <el-icon size="20">
        <CircleCheck v-if="overallStatus === 'ok'" />
        <Warning v-else />
      </el-icon>
      <span>{{ overallStatus === 'ok' ? '所有服务运行正常' : '部分服务不可用，请检查依赖' }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { healthAPI } from '../api'
import { Refresh, CircleCheck, CircleClose, Warning } from '@element-plus/icons-vue'

const loading = ref(false)
const services = reactive({})
const overallStatus = ref('')

const serviceLabels = {
  database: 'PostgreSQL 数据库',
  chromadb: 'ChromaDB 向量库',
  ollama_llm: 'Ollama LLM (qwen3.5:2b)',
  ollama_embed: 'Ollama Embedding',
}

onMounted(() => {
  checkHealth()
})

async function checkHealth() {
  loading.value = true
  try {
    const { data } = await healthAPI.check()
    Object.assign(services, data.services)
    overallStatus.value = data.status
  } catch {
    Object.keys(services).forEach((k) => (services[k] = false))
    overallStatus.value = 'degraded'
  }
  loading.value = false
}
</script>

<style scoped>
.status-page {
  padding: 20px;
  height: 100vh;
  overflow-y: auto;
}

.status-page h2 {
  color: #303133;
  margin-bottom: 4px;
}

.subtitle {
  color: #909399;
  margin-bottom: 16px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.status-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border-radius: 12px;
  border: 1px solid #e4e7ed;
  background: #fff;
  transition: all 0.3s;
}

.status-ok {
  border-color: #67c23a;
}

.status-error {
  border-color: #f56c6c;
}

.status-info h4 {
  color: #303133;
  margin-bottom: 4px;
}

.status-info p {
  color: #909399;
  font-size: 14px;
}

.overall-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 14px;
}

.overall-ok {
  background: #f0f9eb;
  color: #67c23a;
}

.overall-degraded {
  background: #fdf6ec;
  color: #e6a23c;
}
</style>
