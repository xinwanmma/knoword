<template>
  <div class="chat-layout">
    <!-- 左侧：历史对话列表 -->
    <div class="chat-sidebar">
      <div class="sidebar-header">
        <h3>对话历史</h3>
        <el-button type="primary" size="small" @click="newChat">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
      <div class="conversation-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conversation-item"
          :class="{ active: currentConvId === conv.id }"
          @click="loadConversation(conv.id)"
        >
          <el-icon><ChatLineRound /></el-icon>
          <span class="conv-title">{{ conv.title }}</span>
          <el-icon class="delete-btn" @click.stop="deleteConversation(conv.id)"><Delete /></el-icon>
        </div>
        <div v-if="conversations.length === 0" class="empty-tip">
          暂无对话记录
        </div>
      </div>
    </div>

    <!-- 右侧：对话区 -->
    <div class="chat-main">
      <!-- 知识库选择栏 -->
      <div class="kb-selector">
        <div class="selector-options">
          <el-radio-group v-model="searchMode" size="small">
            <el-radio-button value="selected">指定知识库</el-radio-button>
            <el-radio-button value="all">搜索全部</el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="searchMode === 'selected'" class="kb-tags">
          <el-checkbox-group v-model="selectedKbIds" :max="10">
            <el-checkbox
              v-for="kb in knowledgeBases"
              :key="kb.id"
              :value="kb.id"
              border
              size="small"
            >
              {{ kb.name }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </div>

      <!-- 消息列表 -->
      <div ref="messagesContainer" class="messages-area">
        <div v-if="messages.length === 0" class="empty-chat">
          <el-icon size="60" color="#c0c4cc"><ChatDotRound /></el-icon>
          <p>开始提问吧</p>
        </div>

        <div v-for="(msg, idx) in messages" :key="idx">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="message-bubble message-user">
            {{ msg.content }}
          </div>

          <!-- AI 回答 -->
          <div v-else class="assistant-block">
            <!-- Agent 标签 -->
            <div class="agent-label">
              <span v-if="msg.agent === 'rag'" class="agent-tag agent-rag">🟢 RAG 助手</span>
              <span v-else class="agent-tag agent-general">🔵 通用助手</span>
            </div>
            <!-- 引用来源 -->
            <div v-if="msg.sources && msg.sources.length > 0" class="sources-section">
              <div class="sources-title">
                <el-icon><Document /></el-icon> 引用来源 ({{ msg.sources.length }})
              </div>
              <div
                v-for="(src, si) in msg.sources"
                :key="si"
                class="source-card"
                @click="toggleSource(idx, si)"
              >
                <div class="source-header">
                  <el-icon><Document /></el-icon>
                  <span>{{ src.filename }}</span>
                  <span v-if="src.page">第{{ src.page }}页</span>
                  <el-tag size="small" type="info">相关度 {{ (src.score * 100).toFixed(0) }}%</el-tag>
                </div>
                <div
                  v-if="expandedSources[`${idx}-${si}`]"
                  class="source-full"
                >
                  {{ src.content }}
                </div>
                <div v-else class="source-content">{{ src.content }}</div>
              </div>
            </div>

            <!-- 回答内容 -->
            <div class="message-bubble message-assistant markdown-body" v-html="renderMarkdown(msg.content)" />
          </div>
        </div>

        <!-- 正在生成的流式回答 -->
        <div v-if="streaming" class="assistant-block">
          <!-- Agent 标签 -->
          <div v-if="streamAgent" class="agent-label">
            <span v-if="streamAgent === 'rag'" class="agent-tag agent-rag">🟢 RAG 助手</span>
            <span v-else class="agent-tag agent-general">🔵 通用助手</span>
          </div>
          <div v-if="streamSources.length > 0" class="sources-section">
            <div class="sources-title">
              <el-icon><Document /></el-icon> 引用来源 ({{ streamSources.length }})
            </div>
            <div v-for="(src, si) in streamSources" :key="si" class="source-card">
              <div class="source-header">
                <el-icon><Document /></el-icon>
                <span>{{ src.filename }}</span>
                <span v-if="src.page">第{{ src.page }}页</span>
              </div>
              <div class="source-content">{{ src.content }}</div>
            </div>
          </div>
          <div class="message-bubble message-assistant markdown-body" v-html="renderMarkdown(streamText)" />
          <span class="typing-cursor" />
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <el-button text @click="showMemoryPanel = true">
          <el-icon size="18"><DataLine /></el-icon>
          <span style="margin-left: 4px; font-size: 12px">记忆</span>
        </el-button>
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入你的问题..."
          :disabled="streaming"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          :disabled="streaming || !inputText.trim()"
          circle
          size="large"
          @click="sendMessage"
        />
      </div>
    </div>
  </div>

  <!-- 记忆面板 -->
  <MemoryPanel :visible="showMemoryPanel" @close="showMemoryPanel = false" />
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch } from 'vue'
import { chatAPI, kbAPI } from '../api'
import { Plus, ChatLineRound, Delete, Document, Promotion, DataLine } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import MemoryPanel from '../components/MemoryPanel.vue'

// 状态
const messages = ref([])
const conversations = ref([])
const currentConvId = ref(null)
const inputText = ref('')
const streaming = ref(false)
const streamText = ref('')
const streamSources = ref([])
const streamAgent = ref('')
const searchMode = ref('selected')
const selectedKbIds = ref([])
const knowledgeBases = ref([])
const expandedSources = reactive({})
const messagesContainer = ref()
const showMemoryPanel = ref(false)
let streamController = null

onMounted(async () => {
  await Promise.all([loadConversations(), loadKnowledgeBases()])
})

async function loadKnowledgeBases() {
  try {
    const { data } = await kbAPI.list()
    knowledgeBases.value = data
  } catch { /* noop */ }
}

async function loadConversations() {
  try {
    const { data } = await chatAPI.history()
    conversations.value = data
  } catch { /* noop */ }
}

async function loadConversation(convId) {
  currentConvId.value = convId
  try {
    const { data } = await chatAPI.getMessages(convId)
    messages.value = data
    scrollToBottom()
  } catch { /* noop */ }
}

function newChat() {
  currentConvId.value = null
  messages.value = []
  inputText.value = ''
}

async function deleteConversation(convId) {
  try {
    await chatAPI.deleteConversation(convId)
    conversations.value = conversations.value.filter((c) => c.id !== convId)
    if (currentConvId.value === convId) {
      newChat()
    }
    ElMessage.success('已删除')
  } catch { /* noop */ }
}

function sendMessage() {
  const query = inputText.value.trim()
  if (!query || streaming.value) return

  // 添加用户消息到界面
  messages.value.push({ role: 'user', content: query })
  inputText.value = ''
  streamText.value = ''
  streamSources.value = []
  streamAgent.value = ''
  streaming.value = true
  scrollToBottom()

  // 构造请求
  const reqData = {
    query,
    search_all: searchMode.value === 'all',
    kb_ids: selectedKbIds.value,
    conversation_id: currentConvId.value,
  }

  // 启动 SSE 流
  streamController = chatAPI.stream(reqData, {
    onToken: (token) => {
      streamText.value += token
      scrollToBottom()
    },
    onSources: (sources) => {
      streamSources.value = sources
    },
    onAgent: (data) => {
      streamAgent.value = data.name
    },
    onDone: (data) => {
      streaming.value = false
      currentConvId.value = data.conversation_id
      messages.value.push({
        role: 'assistant',
        content: streamText.value,
        sources: streamSources.value.length > 0 ? [...streamSources.value] : null,
        agent: streamAgent.value,
      })
      streamText.value = ''
      streamSources.value = []
      streamAgent.value = ''
      loadConversations()
      scrollToBottom()
    },
    onError: (msg) => {
      streaming.value = false
      ElMessage.error(msg)
      streamText.value = ''
      streamSources.value = []
      streamAgent.value = ''
    },
  })
}

function toggleSource(msgIdx, srcIdx) {
  const key = `${msgIdx}-${srcIdx}`
  expandedSources[key] = !expandedSources[key]
}

function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked.parse(text)
  } catch {
    return text
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
}

.chat-sidebar {
  width: 260px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid #e4e7ed;
}

.sidebar-header h3 {
  font-size: 15px;
  color: #303133;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
  font-size: 14px;
  color: #606266;
}

.conversation-item:hover {
  background: #f5f7fa;
}

.conversation-item.active {
  background: #ecf5ff;
  color: #409eff;
}

.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  color: #f56c6c;
}

.conversation-item:hover .delete-btn {
  opacity: 1;
}

.empty-tip {
  text-align: center;
  color: #c0c4cc;
  padding: 40px 0;
  font-size: 14px;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.kb-selector {
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.selector-options {
  margin-bottom: 8px;
}

.kb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
}

.empty-chat p {
  margin-top: 12px;
  font-size: 16px;
}

.assistant-block {
  max-width: 80%;
  margin-bottom: 16px;
}

.sources-section {
  margin-bottom: 8px;
}

.sources-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #909399;
  margin-bottom: 4px;
}

.source-full {
  margin-top: 6px;
  color: #303133;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  border-top: 1px solid #e4e7ed;
  padding-top: 6px;
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}

.agent-label {
  margin-bottom: 4px;
}

.agent-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
}

.agent-rag {
  background: #f0f9eb;
  color: #67c23a;
}

.agent-general {
  background: #ecf5ff;
  color: #409eff;
}
</style>
