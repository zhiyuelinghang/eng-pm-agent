<template>
  <section class="status-supplement">
    <article v-if="mode === 'safety'"><header><span>安全</span><h2>安全风险与管控要求</h2><p>从已维护且未关闭的风险记录中归集安全相关条目，现场状态需结合检查记录核验。</p></header><div v-if="overview?.safety.items.length" class="records"><section v-for="item in overview.safety.items" :key="item.id"><strong>{{ item.name }}</strong><span>{{ item.level }}</span><p>{{ item.requirement || '尚未填写管控要求' }}</p></section></div><p v-else class="empty">暂无安全类风险记录，需继续完善现场安全检查资料。</p></article>
    <template v-else>
      <article><header><span>资料完善情况</span><h2>{{ completenessLabel }}</h2><p>按风险源和质量指标配置的资料要求，核对当前可见文件名称；文件内容与有效性仍需审核。</p></header><p v-if="!overview?.documents.requiredCount" class="empty">尚未配置资料要求，暂不能判定是否完善。</p><div v-else-if="overview.documents.missingMaterials.length" class="records"><span v-for="name in overview.documents.missingMaterials" :key="name">待补齐 / 核验：{{ name }}</span></div><p v-else class="empty">已找到全部要求对应的文件，内容待审核。</p></article>
      <article><header><span>今日新增资料</span><h2>{{ overview?.documents.todayCount ?? '—' }} 份</h2><p>按北京时间当日统计当前可见资料。</p></header><div v-if="overview?.documents.todayFiles.length" class="records"><section v-for="file in overview.documents.todayFiles" :key="file.id"><router-link :to="{ path: '/docs', query: { tab: 'files', search: file.name } }">{{ file.name }}</router-link><p>{{ file.folder_path || '资料库根目录' }}</p></section></div><p v-else class="empty">今日暂无新增资料。</p></article>
    </template>
  </section>
</template>
<script setup lang="ts">
import type { ProjectStatusOverview } from '@/stores/app'
defineProps<{ mode: 'safety' | 'documents'; overview: ProjectStatusOverview | null; completenessLabel?: string }>()
</script>
<style scoped>
.status-supplement { display: grid; gap: 18px; } article { background: white; border: 1px solid #dfe8e5; border-radius: 8px; overflow: hidden; } header { padding: 22px; border-bottom: 1px solid #e8eee9; } header > span { font-size: 12px; color: #4c8067; } h2 { margin: 6px 0; font-size: 20px; color: #183b31; } p { font-size: 14px; line-height: 1.7; color: #64776d; } .records { display: grid; gap: 12px; padding: 20px; font-size: 14px; } .records section { padding: 14px; background: #f5f8f6; border-radius: 6px; } .records section > span { margin-left: 15px; color: #ad692d; } .records > span { color: #9c6330; } .empty { padding: 20px; } a { color: #28604a; }
</style>
