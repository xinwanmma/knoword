<template>
  <div class="memory-panel" :class="{ open: visible }">
    <div class="panel-header">
      <h3>🧠 记忆系统</h3>
      <el-button text @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <el-tabs v-model="activeTab" class="panel-tabs">
      <!-- Mem0 事实记忆 -->
      <el-tab-pane label="事实记忆" name="mem0">
        <div class="tab-content">
          <div v-if="mem0Loading" class="loading">加载中...</div>
          <div v-else-if="mem0Memories.length === 0" class="empty">暂无记忆</div>
          <div v-else>
            <div v-for="(mem, idx) in mem0Memories" :key="mem.id || idx" class="memory-item">
              <div class="memory-text">{{ mem.memory }}</div>
              <el-button text size="small" type="danger" @click="deleteMemory(mem.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
          <el-button size="small" @click="clearMem0" type="danger" plain style="margin-top: 12px">
            清空所有事实记忆
          </el-button>
        </div>
      </el-tab-pane>

      <!-- Memary 知识图谱 -->
      <el-tab-pane label="知识图谱" name="graph">
        <div class="tab-content">
          <div v-if="graphLoading" class="loading">加载中...</div>
          <div v-else>
            <h4>高频实体</h4>
            <div v-if="graphEntities.length === 0" class="empty">暂无实体</div>
            <div v-else class="entity-list">
              <el-tag
                v-for="entity in graphEntities"
                :key="entity.name"
                :type="getEntityType(entity.type)"
                class="entity-tag"
              >
                {{ entity.name }} ({{ entity.mention_count }})
              </el-tag>
            </div>

            <h4 style="margin-top: 16px">最近时间线</h4>
            <div v-if="graphTimeline.length === 0" class="empty">暂无时间线</div>
            <div v-else class="timeline-list">
              <div v-for="(item, idx) in graphTimeline" :key="idx" class="timeline-item">
                <span class="timeline-name">{{ item.name }}</span>
                <el-tag size="small" :type="getEntityType(item.type)">{{ item.type }}</el-tag>
                <span class="timeline-time">{{ formatTime(item.time) }}</span>
              </div>
            </div>
          </div>
          <el-button size="small" @click="clearGraph" type="danger" plain style="margin-top: 12px">
            清空知识图谱
          </el-button>
        </div>
      </el-tab-pane>

      <!-- Store 会话状态 -->
      <el-tab-pane label="会话状态" name="store">
        <div class="tab-content">
          <div v-if="storeLoading" class="loading">加载中...</div>
          <div v-else-if="storeEntries.length === 0" class="empty">暂无会话状态</div>
          <div v-else>
            <div v-for="entry in storeEntries" :key="entry.key" class="store-item">
              <div class="store-key">{{ entry.key }}</div>
              <div class="store-value">{{ formatValue(entry.value) }}</div>
              <el-button text size="small" type="danger" @click="deleteStore(entry.key)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
          <el-button size="small" @click="clearStore" type="danger" plain style="margin-top: 12px">
            清空会话状态
          </el-button>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { memoryAPI, graphAPI, storeAPI } from '../api'
import { Close, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close'])

const activeTab = ref('mem0')

// Mem0
const mem0Memories = ref([])
const mem0Loading = ref(false)

// Graph
const graphEntities = ref([])
const graphTimeline = ref([])
const graphLoading = ref(false)

// Store
const storeEntries = ref([])
const storeLoading = ref(false)

watch(() => props.visible, (val) => {
  if (val) loadAll()
})

function loadAll() {
  loadMem0()
  loadGraph()
  loadStore()
}

async function loadMem0() {
  mem0Loading.value = true
  try {
    const { data } = await memoryAPI.list()
    mem0Memories.value = data.memories || []
  } catch { mem0Memories.value = [] }
  mem0Loading.value = false
}

async function loadGraph() {
  graphLoading.value = true
  try {
    const [entRes, timeRes] = await Promise.all([
      graphAPI.entities(),
      graphAPI.timeline(),
    ])
    graphEntities.value = entRes.data.entities || []
    graphTimeline.value = timeRes.data.timeline || []
  } catch { /* noop */ }
  graphLoading.value = false
}

async function loadStore() {
  storeLoading.value = true
  try {
    const { data } = await storeAPI.list()
    storeEntries.value = data || []
  } catch { storeEntries.value = [] }
  storeLoading.value = false
}

async function deleteMemory(id) {
  try {
    await memoryAPI.delete(id)
    ElMessage.success('已删除')
    loadMem0()
  } catch { /* noop */ }
}

async function clearMem0() {
  try {
    await ElMessageBox.confirm('确定清空所有事实记忆？', '确认', { type: 'warning' })
    await memoryAPI.clear()
    ElMessage.success('已清空')
    loadMem0()
  } catch { /* noop */ }
}

async function clearGraph() {
  try {
    await ElMessageBox.confirm('确定清空知识图谱？', '确认', { type: 'warning' })
    await graphAPI.clear()
    ElMessage.success('已清空')
    loadGraph()
  } catch { /* noop */ }
}

async function deleteStore(key) {
  try {
    await storeAPI.delete(key)
    ElMessage.success('已删除')
    loadStore()
  } catch { /* noop */ }
}

async function clearStore() {
  try {
    await ElMessageBox.confirm('确定清空所有会话状态？', '确认', { type: 'warning' })
    await storeAPI.clear()
    ElMessage.success('已清空')
    loadStore()
  } catch { /* noop */ }
}

function getEntityType(type) {
  const map = { PERSON: '', ORG: 'warning', PROJECT: 'success', TECH: 'info', CONCEPT: '' }
  return map[type] || ''
}

function formatTime(t) {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN')
}

function formatValue(v) {
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
</script>

<style scoped>
.memory-panel {
  position: fixed;
  right: -400px;
  top: 0;
  width: 400px;
  height: 100vh;
  background: #fff;
  box-shadow: -4px 0 12px rgba(0,0,0,0.1);
  z-index: 1000;
  transition: right 0.3s;
  display: flex;
  flex-direction: column;
}

.memory-panel.open {
  right: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e4e7ed;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
}

.panel-tabs {
  flex: 1;
  overflow: hidden;
}

.tab-content {
  padding: 16px;
  overflow-y: auto;
  height: calc(100vh - 120px);
}

.memory-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 8px;
}

.memory-text {
  flex: 1;
  font-size: 13px;
  color: #303133;
  line-height: 1.5;
}

.entity-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.entity-tag {
  cursor: default;
}

.timeline-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
}

.timeline-name {
  font-weight: 500;
  font-size: 13px;
}

.timeline-time {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
}

.store-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 8px;
}

.store-key {
  font-weight: 600;
  font-size: 13px;
  color: #409eff;
}

.store-value {
  flex: 1;
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.loading, .empty {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}
</style>
