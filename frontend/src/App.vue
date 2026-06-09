<template>
  <el-config-provider :locale="zhCn">
    <el-container v-if="userStore.isLoggedIn" class="app-container">
      <!-- 侧边栏 -->
      <el-aside width="220px" class="app-aside">
        <div class="logo">
          <el-icon size="24"><ChatDotRound /></el-icon>
          <span>RAG 知识库</span>
        </div>
        <el-menu
          :default-active="route.path"
          router
          background-color="#001529"
          text-color="#ffffffa6"
          active-text-color="#fff"
          class="aside-menu"
        >
          <el-menu-item index="/">
            <el-icon><ChatLineRound /></el-icon>
            <span>对话</span>
          </el-menu-item>
          <el-menu-item index="/knowledge-base">
            <el-icon><Folder /></el-icon>
            <span>知识库</span>
          </el-menu-item>
          <el-menu-item v-if="userStore.isAdmin" index="/admin">
            <el-icon><Setting /></el-icon>
            <span>管理</span>
          </el-menu-item>
          <el-menu-item index="/status">
            <el-icon><Monitor /></el-icon>
            <span>系统状态</span>
          </el-menu-item>
        </el-menu>
        <div class="user-info">
          <el-dropdown trigger="click">
            <span class="user-name">
              <el-icon><User /></el-icon>
              {{ userStore.user?.username }}
              <el-tag v-if="userStore.isAdmin" size="small" type="warning">管理员</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-aside>

      <!-- 主内容区 -->
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 未登录时直接显示路由内容 -->
    <router-view v-else />
  </el-config-provider>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from './stores/user'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

onMounted(() => {
  if (userStore.isLoggedIn && !userStore.user) {
    userStore.fetchUser()
  }
})

function handleLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-container {
  height: 100vh;
}

.app-aside {
  background: #001529;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
}

.aside-menu {
  flex: 1;
  border-right: none;
}

.user-info {
  padding: 12px 16px;
  border-top: 1px solid #ffffff1a;
}

.user-name {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #ffffffa6;
  font-size: 14px;
  cursor: pointer;
}

.user-name:hover {
  color: #fff;
}

.app-main {
  background: #f5f7fa;
  padding: 0;
  overflow: hidden;
}
</style>
