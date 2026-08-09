import { createRouter, createWebHistory } from 'vue-router'
import EntryList from './views/EntryList.vue'
import EntryDetail from './views/EntryDetail.vue'
import BatchUpload from './views/BatchUpload.vue'
import Inbox from './views/Inbox.vue'

const routes = [
  { path: '/', name: 'home', component: EntryList },
  { path: '/entries/:id', name: 'entry', component: EntryDetail, props: true },
  { path: '/upload', name: 'upload', component: BatchUpload },
  { path: '/inbox', name: 'inbox', component: Inbox },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
