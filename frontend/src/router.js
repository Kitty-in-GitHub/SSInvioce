import { createRouter, createWebHistory } from 'vue-router'
import EntryList from './views/EntryList.vue'
import EntryDetail from './views/EntryDetail.vue'
import Inbox from './views/Inbox.vue'

const routes = [
  { path: '/', name: 'home', component: EntryList },
  { path: '/entries/:id', name: 'entry', component: EntryDetail, props: true },
  { path: '/inbox', name: 'inbox', component: Inbox },
  { path: '/upload', redirect: '/' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
